from typing import Any
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.cache import cache

from parameterized import parameterized
from rest_framework import status

from posthog.models.project_secret_api_key import ProjectSecretAPIKey
from posthog.models.team import Team
from posthog.models.utils import hash_key_value

from products.business_knowledge.backend import libraries, logic
from products.business_knowledge.backend.models import KnowledgeDocument, SafetyVerdict


@patch("posthog.api.embedding_worker.generate_embedding", side_effect=Exception("unavailable"))
@patch("posthoganalytics.feature_enabled", return_value=True)
class TestProjectSecretKeyAccess(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        text = "\n\n".join(f"Paragraph {i}: {'lorem ipsum dolor sit amet ' * 50}" for i in range(5))
        source = logic.create_text_source(team_id=self.team.id, created_by_id=self.user.id, name="Docs", text=text)
        KnowledgeDocument.objects.unscoped().filter(source_id=source.id).update(safety_verdict=SafetyVerdict.SAFE)
        self.document = KnowledgeDocument.objects.unscoped().get(source_id=source.id)
        self.library = libraries.create_library(self.team.id, "Public docs")
        self.client.logout()

    def _base(self, team: Team | None = None) -> str:
        return f"/api/projects/{(team or self.team).id}/business_knowledge"

    def _use_key(self, team: Team | None = None, scopes: list[str] | None = None) -> None:
        team = team or self.team
        token = f"phs_{'a' * 35}{team.id}"
        ProjectSecretAPIKey.objects.create(
            team=team,
            label=f"agent {team.id}",
            mask_value="phs_...aaaa",
            secure_value=hash_key_value(token),
            scopes=["business_knowledge:read"] if scopes is None else scopes,
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def _child_environment(self) -> Team:
        return Team.objects.create(
            organization=self.organization,
            parent_team=self.team,
            project=self.team.project,
            name="Child environment",
        )

    @parameterized.expand(
        [
            ("search", "/documents/search/?query=lorem"),
            ("window", "/documents/{document}/window/?around_ordinal=2"),
            ("library_list", "/libraries/"),
            ("library_retrieve", "/libraries/{library}/"),
        ]
    )
    def test_read_key_reads_knowledge(self, _ff: Any, _embed: Any, _name: str, path: str) -> None:
        self._use_key()
        response = self.client.get(self._base() + path.format(document=self.document.id, library=self.library.id))
        assert response.status_code == status.HTTP_200_OK, response.content

    def test_search_returns_the_project_content(self, _ff: Any, _embed: Any) -> None:
        self._use_key()
        response = self.client.get(f"{self._base()}/documents/search/?query=lorem")
        assert response.status_code == status.HTTP_200_OK, response.content
        assert {hit["document_id"] for hit in response.json()} == {str(self.document.id)}

    @parameterized.expand(
        [
            ("source_list", "get", "/sources/", None),
            ("source_create", "post", "/sources/", {"name": "Pasted", "text": "content"}),
            ("library_create", "post", "/libraries/", {"name": "Internal"}),
            ("library_delete", "delete", "/libraries/{library}/", None),
            ("repository_status", "get", "/repositories/status/", None),
            ("settings", "get", "/settings/", None),
            ("playground_chats", "get", "/playground/chats/", None),
        ]
    )
    def test_read_key_reaches_nothing_else(
        self, _ff: Any, _embed: Any, _name: str, method: str, path: str, body: dict[str, str] | None
    ) -> None:
        self._use_key()
        response = getattr(self.client, method)(
            self._base() + path.format(library=self.library.id), body, format="json"
        )
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN), response.content

    def test_key_without_the_scope_is_forbidden(self, _ff: Any, _embed: Any) -> None:
        self._use_key(scopes=["logs:read"])
        response = self.client.get(f"{self._base()}/documents/search/?query=lorem")
        assert response.status_code == status.HTTP_403_FORBIDDEN, response.content

    @parameterized.expand(
        [
            ("search", "/documents/search/?query=lorem"),
            ("window", "/documents/{document}/window/?around_ordinal=2"),
            ("library_list", "/libraries/"),
        ]
    )
    def test_key_from_another_project_is_forbidden(self, _ff: Any, _embed: Any, _name: str, path: str) -> None:
        other = Team.objects.create(organization=self.organization, name="Other project")
        self._use_key(team=other)
        response = self.client.get(self._base() + path.format(document=self.document.id))
        assert response.status_code == status.HTTP_403_FORBIDDEN, response.content

    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    @patch("products.business_knowledge.backend.api.throttles.KnowledgeBurstRateThrottle.rate", new="1/minute")
    def test_key_requests_are_throttled(self, _enabled: Any, _ff: Any, _embed: Any) -> None:
        cache.clear()
        self.addCleanup(cache.clear)
        self._use_key()
        assert self.client.get(f"{self._base()}/libraries/").status_code == status.HTTP_200_OK
        assert self.client.get(f"{self._base()}/libraries/").status_code == status.HTTP_429_TOO_MANY_REQUESTS

    @parameterized.expand(
        [
            ("search", "/documents/search/?query=lorem"),
            ("window", "/documents/{document}/window/?around_ordinal=2"),
            ("library_list", "/libraries/"),
        ]
    )
    def test_child_environment_key_does_not_read_parent_knowledge(
        self, _ff: Any, _embed: Any, _name: str, path: str
    ) -> None:
        child = self._child_environment()
        self._use_key(team=child)
        response = self.client.get(self._base(child) + path.format(document=self.document.id))
        assert response.status_code in (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND), response.content

    @parameterized.expand(
        [
            ("search", "/repositories/search/?query=billing&library_id={library}"),
            ("file", "/repositories/file/?repo=acme/billing&path=src/billing.py&library_id={library}"),
        ]
    )
    def test_child_environment_key_cannot_tell_which_parent_libraries_exist(
        self, _ff: Any, _embed: Any, _name: str, path: str
    ) -> None:
        child = self._child_environment()
        self._use_key(team=child)
        existing = self.client.get(self._base(child) + path.format(library=self.library.id))
        unknown = self.client.get(self._base(child) + path.format(library=uuid4()))
        assert existing.status_code == status.HTTP_403_FORBIDDEN, existing.content
        assert unknown.status_code == status.HTTP_403_FORBIDDEN, unknown.content
