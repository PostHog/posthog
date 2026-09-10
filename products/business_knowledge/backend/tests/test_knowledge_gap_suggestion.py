import uuid

from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.models.organization import Organization
from posthog.models.project import Project
from posthog.models.team import Team

from products.business_knowledge.backend import logic
from products.business_knowledge.backend.models import GapStatus, KnowledgeGapSuggestion


class TestUpsertKnowledgeGaps(BaseTest):
    def _ticket_id(self) -> str:
        return str(uuid.uuid4())

    def test_basic_upsert(self) -> None:
        tid = self._ticket_id()
        created = logic.upsert_knowledge_gaps(
            team_id=self.team.id,
            ticket_id=tid,
            topics=["How to configure webhooks", "Rate limiting"],
            ticket_type="how_to",
            outcome="escalated_no_reply",
        )
        assert created == 2
        assert KnowledgeGapSuggestion.objects.for_team(self.team.id).filter(ticket_id=tid).count() == 2

    def test_idempotent_under_retry(self) -> None:
        tid = self._ticket_id()
        topics = ["Billing FAQ"]
        logic.upsert_knowledge_gaps(self.team.id, tid, topics)
        logic.upsert_knowledge_gaps(self.team.id, tid, topics)
        assert KnowledgeGapSuggestion.objects.for_team(self.team.id).filter(ticket_id=tid).count() == 1

    def test_normalization(self) -> None:
        tid = self._ticket_id()
        logic.upsert_knowledge_gaps(self.team.id, tid, ["  UPPERCASE Topic  "])
        gap = KnowledgeGapSuggestion.objects.for_team(self.team.id).get(ticket_id=tid)
        assert gap.normalized_topic == "uppercase topic"
        assert gap.topic == "UPPERCASE Topic"

    @parameterized.expand(["", "  ", "parse_failure"])
    def test_filters_noise(self, noise_topic: str) -> None:
        tid = self._ticket_id()
        created = logic.upsert_knowledge_gaps(self.team.id, tid, [noise_topic])
        assert created == 0

    def test_cross_team_isolation(self) -> None:
        other_org = Organization.objects.create(name="other_org")
        other_project = Project.objects.create(id=Team.objects.increment_id_sequence(), organization=other_org)
        other_team = Team.objects.create(id=other_project.id, project=other_project, organization=other_org)

        tid = self._ticket_id()
        logic.upsert_knowledge_gaps(self.team.id, tid, ["Shared topic"])
        logic.upsert_knowledge_gaps(other_team.id, tid, ["Shared topic"])

        assert KnowledgeGapSuggestion.objects.for_team(self.team.id).count() == 1
        assert KnowledgeGapSuggestion.objects.for_team(other_team.id).count() == 1


class TestAggregateGapSuggestions(BaseTest):
    def test_groups_by_normalized_topic(self) -> None:
        for _ in range(3):
            logic.upsert_knowledge_gaps(self.team.id, str(uuid.uuid4()), ["Webhook setup"], ticket_type="how_to")
        logic.upsert_knowledge_gaps(self.team.id, str(uuid.uuid4()), ["Rate limits"])

        agg = logic.aggregate_gap_suggestions(self.team.id)
        topics = {a.normalized_topic: a.ticket_count for a in agg}
        assert topics["webhook setup"] == 3
        assert topics["rate limits"] == 1

    def test_only_pending(self) -> None:
        tid = str(uuid.uuid4())
        logic.upsert_knowledge_gaps(self.team.id, tid, ["Dismissed topic"])
        logic.set_gap_status(self.team.id, normalized_topic="dismissed topic", status=GapStatus.DISMISSED)

        agg = logic.aggregate_gap_suggestions(self.team.id)
        assert len(agg) == 0


class TestSetGapStatus(BaseTest):
    def test_accept_cluster(self) -> None:
        for _ in range(2):
            logic.upsert_knowledge_gaps(self.team.id, str(uuid.uuid4()), ["Same topic"])

        updated = logic.set_gap_status(self.team.id, normalized_topic="same topic", status=GapStatus.ACCEPTED)
        assert updated == 2
        assert KnowledgeGapSuggestion.objects.for_team(self.team.id).filter(status=GapStatus.ACCEPTED).count() == 2

    def test_dismiss_single(self) -> None:
        tid = str(uuid.uuid4())
        logic.upsert_knowledge_gaps(self.team.id, tid, ["Topic A"])
        gap = KnowledgeGapSuggestion.objects.for_team(self.team.id).first()
        assert gap is not None
        logic.set_gap_status(self.team.id, suggestion_id=gap.id, status=GapStatus.DISMISSED)
        gap.refresh_from_db()
        assert gap.status == GapStatus.DISMISSED


@patch("posthoganalytics.feature_enabled", return_value=True)
class TestKnowledgeGapSuggestionAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.url = f"/api/projects/{self.team.id}/business_knowledge/gap_suggestions/"

    def test_list_aggregated(self, _ff) -> None:
        for _ in range(2):
            logic.upsert_knowledge_gaps(self.team.id, str(uuid.uuid4()), ["Setup help"])
        response = self.client.get(self.url)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        results = data if isinstance(data, list) else data.get("results", data)
        assert len(results) == 1
        assert results[0]["ticket_count"] == 2

    def test_list_per_ticket(self, _ff) -> None:
        tid = str(uuid.uuid4())
        logic.upsert_knowledge_gaps(self.team.id, tid, ["Topic A", "Topic B"])
        response = self.client.get(f"{self.url}?ticket_id={tid}")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        results = data if isinstance(data, list) else data.get("results", data)
        assert len(results) == 2

    def test_dismiss_action(self, _ff) -> None:
        tid = str(uuid.uuid4())
        logic.upsert_knowledge_gaps(self.team.id, tid, ["Dismiss me"])
        gap = KnowledgeGapSuggestion.objects.for_team(self.team.id).first()
        assert gap is not None
        response = self.client.post(f"{self.url}{gap.id}/dismiss/")
        assert response.status_code == status.HTTP_200_OK
        gap.refresh_from_db()
        assert gap.status == GapStatus.DISMISSED

    def test_accept_action(self, _ff) -> None:
        tid = str(uuid.uuid4())
        logic.upsert_knowledge_gaps(self.team.id, tid, ["Accept me"])
        gap = KnowledgeGapSuggestion.objects.for_team(self.team.id).first()
        assert gap is not None
        response = self.client.post(f"{self.url}{gap.id}/accept/", {}, format="json")
        assert response.status_code == status.HTTP_200_OK
        gap.refresh_from_db()
        assert gap.status == GapStatus.ACCEPTED

    def test_team_isolation(self, _ff) -> None:
        other_org = Organization.objects.create(name="other_org")
        other_project = Project.objects.create(id=Team.objects.increment_id_sequence(), organization=other_org)
        other_team = Team.objects.create(id=other_project.id, project=other_project, organization=other_org)
        logic.upsert_knowledge_gaps(other_team.id, str(uuid.uuid4()), ["Other team topic"])

        response = self.client.get(self.url)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        results = data if isinstance(data, list) else data.get("results", data)
        assert len(results) == 0

    def test_aggregate_does_not_expose_ticket_ids(self, _ff) -> None:
        logic.upsert_knowledge_gaps(self.team.id, str(uuid.uuid4()), ["Leaky topic"])
        response = self.client.get(self.url)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        results = data if isinstance(data, list) else data.get("results", data)
        assert len(results) == 1
        assert "sample_ticket_ids" not in results[0]


@patch("posthoganalytics.feature_enabled", return_value=True)
class TestKnowledgeGapSuggestionScopes(APIBaseTest):
    """A token must carry `ticket:read` to reach ticket-derived data via the per-ticket path."""

    def setUp(self) -> None:
        super().setUp()
        self.url = f"/api/projects/{self.team.id}/business_knowledge/gap_suggestions/"
        self.ticket_id = str(uuid.uuid4())
        logic.upsert_knowledge_gaps(self.team.id, self.ticket_id, ["Topic A"])

    def _auth_with_pak(self, scopes: list[str]) -> None:
        key = self.create_personal_api_key_with_scopes(scopes)
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {key}")

    def test_aggregate_allowed_with_business_knowledge_read_only(self, _ff) -> None:
        self._auth_with_pak(["business_knowledge:read"])
        response = self.client.get(self.url)
        assert response.status_code == status.HTTP_200_OK

    def test_per_ticket_denied_without_ticket_read(self, _ff) -> None:
        self._auth_with_pak(["business_knowledge:read"])
        response = self.client.get(f"{self.url}?ticket_id={self.ticket_id}")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_per_ticket_allowed_with_ticket_read(self, _ff) -> None:
        self._auth_with_pak(["business_knowledge:read", "ticket:read"])
        response = self.client.get(f"{self.url}?ticket_id={self.ticket_id}")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        results = data if isinstance(data, list) else data.get("results", data)
        assert len(results) == 1

    def _first_gap_id(self) -> str:
        gap = KnowledgeGapSuggestion.objects.for_team(self.team.id).first()
        assert gap is not None
        return str(gap.id)

    @parameterized.expand(["accept", "dismiss"])
    def test_detail_action_denied_without_ticket_read(self, _ff, verb: str) -> None:
        gap_id = self._first_gap_id()
        self._auth_with_pak(["business_knowledge:write"])
        response = self.client.post(f"{self.url}{gap_id}/{verb}/", {}, format="json")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    @parameterized.expand(["accept", "dismiss"])
    def test_detail_action_allowed_with_ticket_read(self, _ff, verb: str) -> None:
        gap_id = self._first_gap_id()
        self._auth_with_pak(["business_knowledge:write", "ticket:read"])
        response = self.client.post(f"{self.url}{gap_id}/{verb}/", {}, format="json")
        assert response.status_code == status.HTTP_200_OK
