from typing import Any
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.models.organization import OrganizationMembership
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.project_secret_api_key import ProjectSecretAPIKey
from posthog.models.team import Team
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.business_knowledge.backend import libraries, logic
from products.business_knowledge.backend.models import (
    KnowledgeDocument,
    KnowledgeKeyLibrary,
    KnowledgeLibrary,
    SafetyVerdict,
)

READ_ROUTES = [
    ("search", "/documents/search/?query=lorem"),
    ("window", "/documents/{document}/window/?around_ordinal=0"),
    ("window_unknown_document", "/documents/{unknown}/window/?around_ordinal=0"),
    ("library_list", "/libraries/"),
    ("library_retrieve", "/libraries/{library}/"),
    ("access", "/access/"),
    ("repository_search", "/repositories/search/?query=billing"),
    ("repository_file", "/repositories/file/?repo=acme/billing&path=src/billing.py"),
]


@patch("posthog.api.embedding_worker.generate_embedding", side_effect=Exception("unavailable"))
@patch("posthoganalytics.feature_enabled", return_value=True)
class TestLibraryLimitedKeys(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.base = f"/api/projects/{self.team.id}/business_knowledge"
        self.public, self.public_document = self._library_with_document("Public docs")
        self.internal, self.internal_document = self._library_with_document("Internal docs")

    def _library_with_document(self, name: str) -> tuple[KnowledgeLibrary, KnowledgeDocument]:
        source = logic.create_text_source(
            team_id=self.team.id, created_by_id=self.user.id, name=name, text=f"{name}: lorem ipsum dolor sit amet"
        )
        KnowledgeDocument.objects.unscoped().filter(source_id=source.id).update(safety_verdict=SafetyVerdict.SAFE)
        library = libraries.create_library(self.team.id, name)
        libraries.replace_library_sources(self.team.id, library.id, [source.id])
        return library, KnowledgeDocument.objects.unscoped().get(source_id=source.id)

    def _use_key(self, library: KnowledgeLibrary | None, label: str = "agent") -> ProjectSecretAPIKey:
        token = f"phs_{uuid4().hex}{uuid4().hex}"
        key = ProjectSecretAPIKey.objects.create(
            team=self.team,
            label=label,
            mask_value="phs_...aaaa",
            secure_value=hash_key_value(token),
            scopes=["business_knowledge:read"],
        )
        if library is not None:
            KnowledgeKeyLibrary.objects.unscoped().create(team=self.team, key=key, library=library)
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        return key

    def _searched_documents(self, query: str = "") -> set[str]:
        response = self.client.get(f"{self.base}/documents/search/?query=lorem{query}")
        assert response.status_code == status.HTTP_200_OK, response.content
        return {hit["document_id"] for hit in response.json()}

    def test_limited_key_searches_only_its_library(self, _ff: Any, _embed: Any) -> None:
        self._use_key(None, "whole project")
        assert self._searched_documents() == {str(self.public_document.id), str(self.internal_document.id)}

        self._use_key(self.public)
        assert self._searched_documents() == {str(self.public_document.id)}
        assert self._searched_documents(f"&library_id={self.public.id}") == {str(self.public_document.id)}

    @parameterized.expand([("limited", True), ("whole_project", False)])
    def test_key_learns_its_project_and_library_without_naming_the_project(
        self, _ff: Any, _embed: Any, _name: str, limited: bool
    ) -> None:
        self._use_key(self.public if limited else None)
        response = self.client.get("/api/projects/@current/business_knowledge/access/")
        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.json() == {
            "project_id": self.team.id,
            "is_limited": limited,
            "library_id": str(self.public.id) if limited else None,
        }

    def test_limited_key_lists_only_its_library(self, _ff: Any, _embed: Any) -> None:
        self._use_key(self.public)
        response = self.client.get(f"{self.base}/libraries/")
        assert response.status_code == status.HTTP_200_OK, response.content
        assert [library["id"] for library in response.json()] == [str(self.public.id)]

    def test_limited_key_reads_documents_in_its_library(self, _ff: Any, _embed: Any) -> None:
        self._use_key(self.public)
        response = self.client.get(f"{self.base}/documents/{self.public_document.id}/window/?around_ordinal=0")
        assert response.status_code == status.HTTP_200_OK, response.content
        assert ["Public docs" in chunk["content"] for chunk in response.json()] == [True]

    @parameterized.expand(
        [
            ("search", "/documents/search/?query=lorem&library_id={library}"),
            ("window", "/documents/{document}/window/?around_ordinal=0"),
            ("library_retrieve", "/libraries/{library}/"),
            ("repository_search", "/repositories/search/?query=billing&library_id={library}"),
            ("repository_file", "/repositories/file/?repo=acme/billing&path=src/billing.py&library_id={library}"),
        ]
    )
    def test_limited_key_gets_not_found_outside_its_library(self, _ff: Any, _embed: Any, _name: str, path: str) -> None:
        self._use_key(self.public)
        response = self.client.get(
            self.base + path.format(library=self.internal.id, document=self.internal_document.id)
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND, response.content

    @parameterized.expand(READ_ROUTES)
    def test_key_reads_nothing_after_its_library_is_deleted(self, _ff: Any, _embed: Any, _name: str, path: str) -> None:
        self._use_key(self.public)
        libraries.delete_library(self.team.id, self.public.id)
        response = self.client.get(
            self.base + path.format(library=self.internal.id, document=self.internal_document.id, unknown=uuid4())
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN, response.content

    def test_key_deleted_during_a_request_reads_nothing(self, _ff: Any, _embed: Any) -> None:
        key = self._use_key(self.public)

        def find_then_delete(_token: str) -> ProjectSecretAPIKey:
            ProjectSecretAPIKey.objects.filter(pk=key.pk).delete()
            return key

        with patch("posthog.auth.find_project_secret_api_key", side_effect=find_then_delete):
            response = self.client.get(f"{self.base}/documents/search/?query=lorem")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED, response.content
        assert not KnowledgeKeyLibrary.objects.unscoped().filter(key_id=key.pk).exists()

    def _create_key(self, library_id: Any, label: str = "Docs agent") -> Any:
        return self.client.post(
            f"{self.base}/keys/", {"label": label, "library_id": library_id and str(library_id)}, format="json"
        )

    def _become_admin(self) -> None:
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

    def test_created_key_reads_only_the_chosen_library(self, _ff: Any, _embed: Any) -> None:
        self._become_admin()
        response = self._create_key(self.public.id)
        assert response.status_code == status.HTTP_201_CREATED, response.content
        created = response.json()
        assert created["is_limited"] is True
        assert created["library_id"] == str(self.public.id)

        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {created['value']}")
        assert self._searched_documents() == {str(self.public_document.id)}

    def test_key_created_without_a_library_reads_all_business_knowledge(self, _ff: Any, _embed: Any) -> None:
        self._become_admin()
        response = self._create_key(None)
        assert response.status_code == status.HTTP_201_CREATED, response.content
        created = response.json()
        assert (created["is_limited"], created["library_id"]) == (False, None)

        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {created['value']}")
        assert self._searched_documents() == {str(self.public_document.id), str(self.internal_document.id)}

    def test_request_that_names_no_library_creates_no_key(self, _ff: Any, _embed: Any) -> None:
        self._become_admin()
        response = self.client.post(f"{self.base}/keys/", {"label": "Docs agent"}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert not ProjectSecretAPIKey.objects.filter(team=self.team).exists()

    def test_unknown_library_creates_no_key(self, _ff: Any, _embed: Any) -> None:
        self._become_admin()
        response = self._create_key(uuid4())
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert not ProjectSecretAPIKey.objects.filter(team=self.team).exists()

    def test_member_who_cannot_manage_the_project_creates_no_key(self, _ff: Any, _embed: Any) -> None:
        response = self._create_key(self.public.id)
        assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
        assert not ProjectSecretAPIKey.objects.filter(team=self.team).exists()

    def test_personal_key_without_the_knowledge_scope_creates_no_key(self, _ff: Any, _embed: Any) -> None:
        self._become_admin()
        token = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            user=self.user, label="project only", secure_value=hash_key_value(token), scopes=["project:write"]
        )
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        response = self._create_key(self.public.id)
        assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
        assert not ProjectSecretAPIKey.objects.filter(team=self.team).exists()

    @parameterized.expand([("list", "get"), ("create", "post")])
    def test_child_environment_is_sent_to_the_parent_project(
        self, _ff: Any, _embed: Any, _name: str, method: str
    ) -> None:
        self._become_admin()
        child = Team.objects.create(
            organization=self.organization, parent_team=self.team, project=self.team.project, name="Child environment"
        )
        response = getattr(self.client, method)(
            f"/api/projects/{child.id}/business_knowledge/keys/",
            {"label": "Docs agent", "library_id": str(self.public.id)},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert f"project ID {self.team.id}" in response.json()["detail"]

    def test_list_shows_what_each_key_reads(self, _ff: Any, _embed: Any) -> None:
        whole = self._use_key(None, "whole project")
        limited = self._use_key(self.public, "public")
        orphaned = self._use_key(self.internal, "internal")
        ProjectSecretAPIKey.objects.create(team=self.team, label="flags", scopes=["feature_flag:read"])
        libraries.delete_library(self.team.id, self.internal.id)
        self.client.credentials()
        self.client.force_login(self.user)

        response = self.client.get(f"{self.base}/keys/")

        assert response.status_code == status.HTTP_200_OK, response.content
        assert {key["id"]: (key["is_limited"], key["library_id"], key["value"]) for key in response.json()} == {
            whole.id: (False, None, None),
            limited.id: (True, str(self.public.id), None),
            orphaned.id: (True, None, None),
        }
