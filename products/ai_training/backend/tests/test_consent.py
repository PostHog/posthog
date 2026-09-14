from uuid import UUID

from unittest.mock import AsyncMock, MagicMock, patch

from django.core.management import call_command
from django.db import DatabaseError
from django.test import TestCase, override_settings

from parameterized import parameterized

from posthog.api.person import PersonViewSet
from posthog.models import Organization, Person, Team
from posthog.models.team.util import delete_team_records

from products.ai_training.backend.facade.api import queue_training_deletion, record_training_consent
from products.ai_training.backend.models import AITrainingConsent, AITrainingPrivacyRequest


@override_settings(AI_RESEARCH_REPLAY_PRIVACY_TABLE="test-table")
class TestAITrainingConsentOutbox(TestCase):
    @parameterized.expand([("",), ("test-table",)])
    def test_reconsent_has_a_new_timestamp_and_rollback_preserves_the_previous_state(self, table: str) -> None:
        with self.settings(AI_RESEARCH_REPLAY_PRIVACY_TABLE=table):
            organization_id = UUID("00000000-0000-0000-0000-000000000007")
            with record_training_consent(organization_id, True):
                pass
            first = AITrainingConsent.objects.get(organization_id=organization_id)
            with record_training_consent(organization_id, False):
                pass
            with record_training_consent(organization_id, True):
                pass
            resumed = AITrainingConsent.objects.get(organization_id=organization_id)
            self.assertGreater(resumed.granted_at_ms, first.granted_at_ms)
            self.assertEqual(resumed.revision, 3)
            with self.assertRaises(ValueError), record_training_consent(organization_id, False):
                raise ValueError("rollback")
            self.assertTrue(AITrainingConsent.objects.get(organization_id=organization_id).allowed)
            self.assertEqual(AITrainingPrivacyRequest.objects.unscoped().count(), 3)

    def test_deployment_initialization_preserves_existing_consent_and_is_safe_to_retry(self) -> None:
        existing_id = UUID("00000000-0000-0000-0000-000000000007")
        missing_id = UUID("00000000-0000-0000-0000-000000000008")
        denied_id = UUID("00000000-0000-0000-0000-000000000009")
        Organization.objects.bulk_create(
            [
                Organization(id=existing_id, name="Existing", slug="existing", is_ai_training_opted_in=True),
                Organization(id=missing_id, name="Missing", slug="missing", is_ai_training_opted_in=True),
                Organization(id=denied_id, name="Denied", slug="denied", is_ai_training_opted_in=False),
            ]
        )
        with self.settings(AI_RESEARCH_REPLAY_PRIVACY_TABLE=""), record_training_consent(existing_id, True):
            pass
        existing = AITrainingConsent.objects.get(organization_id=existing_id)
        for _ in range(2):
            call_command("initialize_ai_training_consent")
            self.assertEqual(
                AITrainingConsent.objects.get(organization_id=existing_id).granted_at_ms, existing.granted_at_ms
            )
            self.assertTrue(AITrainingConsent.objects.get(organization_id=missing_id).allowed)
            self.assertFalse(AITrainingConsent.objects.get(organization_id=denied_id).allowed)
            self.assertEqual(AITrainingPrivacyRequest.objects.unscoped().count(), 3)
        with record_training_consent(existing_id, False):
            Organization.objects.filter(id=existing_id).update(is_ai_training_opted_in=False)
        call_command("initialize_ai_training_consent")
        self.assertFalse(AITrainingConsent.objects.get(organization_id=existing_id).allowed)
        self.assertEqual(AITrainingPrivacyRequest.objects.unscoped().count(), 4)

    def test_queue_filters_invalid_session_ids_and_retains_distinct_ids_in_bulk(self) -> None:
        session_id = "01a09f92-e780-7000-8000-000000000001"
        queue_training_deletion(7, "session", ["invalid", session_id.upper(), session_id])
        request = AITrainingPrivacyRequest.objects.for_team(7).get()
        self.assertEqual(request.identifiers, [session_id])
        queue_training_deletion(7, "distinct", [f"distinct-{index}" for index in range(1001)])
        self.assertEqual(AITrainingPrivacyRequest.objects.for_team(7).filter(kind="distinct").count(), 2)

    @parameterized.expand([(False,), (True,)])
    def test_bulk_person_deletion_queues_resolved_and_unresolved_distinct_ids_once(self, keep_person: bool) -> None:
        person = Person(id=1, uuid=UUID("00000000-0000-0000-0000-000000000007"))
        person._distinct_ids = ["known", "alias"]
        view = MagicMock(team_id=7)
        request = MagicMock(user=None)
        temporal = MagicMock()
        temporal.start_workflow = AsyncMock()
        with (
            patch("posthog.api.person.resolve_persons_for_deletion", return_value=[person]),
            patch("posthog.models.person.bulk_delete._batched_get_distinct_ids_for_persons", return_value={}),
            patch("posthog.models.person.bulk_delete.delete_person"),
            patch("posthog.models.person.bulk_delete.delete_persons_from_postgres"),
            patch("posthog.models.person.bulk_delete.sync_connect", return_value=temporal),
        ):
            PersonViewSet._bulk_delete_persons(
                view,
                request,
                distinct_ids=["known", "missing"],
                delete_recordings=True,
                keep_person=keep_person,
            )
        queued = AITrainingPrivacyRequest.objects.for_team(7).get()
        self.assertEqual(queued.kind, "distinct")
        self.assertEqual(queued.identifiers, ["alias", "known", "missing"])

    def test_team_deletion_and_privacy_request_commit_together(self) -> None:
        with patch.object(Team, "objects") as teams:
            teams.select_for_update.return_value.filter.return_value = [Team(id=7)]
            teams.filter.return_value.delete.side_effect = RuntimeError("team delete failed")
            with self.assertRaisesRegex(RuntimeError, "team delete failed"):
                delete_team_records([7])
            self.assertFalse(AITrainingPrivacyRequest.objects.for_team(7).exists())

            teams.filter.return_value.delete.side_effect = None
            delete_team_records([7])
            self.assertEqual(AITrainingPrivacyRequest.objects.for_team(7).get().kind, "team")

    def test_team_deletion_does_not_run_if_privacy_request_write_fails(self) -> None:
        with (
            patch.object(Team, "objects") as teams,
            patch("django.db.models.query.QuerySet.bulk_create", side_effect=DatabaseError("outbox unavailable")),
        ):
            teams.select_for_update.return_value.filter.return_value = [Team(id=7)]
            with self.assertRaisesRegex(DatabaseError, "outbox unavailable"):
                delete_team_records([7])
            teams.filter.return_value.delete.assert_not_called()
