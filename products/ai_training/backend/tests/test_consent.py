from uuid import UUID

from unittest.mock import AsyncMock, MagicMock, patch

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

    @parameterized.expand([(True,), (False,)])
    def test_first_consent_record_preserves_legacy_opt_in_until_a_new_grant(self, legacy_allowed: bool) -> None:
        organization_id = UUID("00000000-0000-0000-0000-000000000007")
        Organization.objects.bulk_create(
            [Organization(id=organization_id, name="Example", slug="example", is_ai_training_opted_in=legacy_allowed)]
        )
        for _ in range(2):
            with record_training_consent(organization_id, legacy_allowed):
                pass
        initial = AITrainingConsent.objects.get(organization_id=organization_id)
        self.assertEqual(initial.allowed, legacy_allowed)
        self.assertEqual(initial.granted_at_ms, 0)
        self.assertEqual(initial.revision, 1)
        self.assertEqual(AITrainingPrivacyRequest.objects.unscoped().count(), 1)
        with record_training_consent(organization_id, False):
            Organization.objects.filter(id=organization_id).update(is_ai_training_opted_in=False)
        with record_training_consent(organization_id, True):
            Organization.objects.filter(id=organization_id).update(is_ai_training_opted_in=True)
        resumed = AITrainingConsent.objects.get(organization_id=organization_id)
        self.assertGreater(resumed.granted_at_ms, 0)
        self.assertEqual(resumed.revision, 3 if legacy_allowed else 2)

    def test_first_opt_in_does_not_inherit_a_legacy_grant(self) -> None:
        organization_id = UUID("00000000-0000-0000-0000-000000000007")
        Organization.objects.bulk_create(
            [Organization(id=organization_id, name="Example", slug="example", is_ai_training_opted_in=False)]
        )
        with record_training_consent(organization_id, True):
            Organization.objects.filter(id=organization_id).update(is_ai_training_opted_in=True)
        self.assertGreater(AITrainingConsent.objects.get(organization_id=organization_id).granted_at_ms, 0)

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
