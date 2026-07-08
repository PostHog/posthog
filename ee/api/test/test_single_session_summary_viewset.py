import copy
from datetime import UTC, datetime

import pytest
from posthog.test.base import APIBaseTest

from posthog.constants import AvailableFeature
from posthog.models import Organization, OrganizationMembership, Team, User
from posthog.session_recordings.models.session_recording import SessionRecording

from products.replay.backend.models.session_summaries import SessionSummaryRunMeta, SingleSessionSummary

from ee.hogai.session_summaries.session.output_data import SessionSummarySerializer
from ee.hogai.session_summaries.tests.conftest import get_mock_enriched_llm_json_response
from ee.models.rbac.access_control import AccessControl


class TestSingleSessionSummaryViewSet(APIBaseTest):
    def _url(self, session_id: str | None = None) -> str:
        base = f"/api/projects/{self.team.id}/single_session_summaries/"
        return base if session_id is None else f"{base}{session_id}/"

    def _make_summary(
        self,
        session_id: str,
        *,
        team: Team | None = None,
        success: bool | None = True,
        exception_event_ids: list[str] | None = None,
        focus_area: str | None = None,
        visual_confirmation: bool = False,
        model_used: str = "gpt-4o",
        distinct_id: str | None = "user-1",
        session_duration: int | None = 120,
        session_start_time: datetime | None = None,
    ) -> SingleSessionSummary:
        team = team or self.team
        summary = copy.deepcopy(get_mock_enriched_llm_json_response(session_id))
        if success is None:
            summary.pop("session_outcome", None)
        else:
            summary["session_outcome"]["success"] = success
        return SingleSessionSummary.objects.create(
            team=team,
            session_id=session_id,
            summary=summary,
            exception_event_ids=exception_event_ids or [],
            extra_summary_context={"focus_area": focus_area} if focus_area else None,
            run_metadata={
                "model_used": model_used,
                "visual_confirmation": visual_confirmation,
                "visual_confirmation_results": None,
                "failed_sessions": [],
            },
            distinct_id=distinct_id,
            session_duration=session_duration,
            session_start_time=session_start_time or datetime(2026, 1, 1, tzinfo=UTC),
            created_by=self.user,
        )

    def test_list_returns_only_team_summaries(self) -> None:
        self._make_summary("session-a")
        self._make_summary("session-b")
        other_team = Organization.objects.bootstrap(None)[2]
        self._make_summary("other-team-session", team=other_team)

        response = self.client.get(self._url())

        self.assertEqual(response.status_code, 200)
        body = response.json()
        session_ids = {row["session_id"] for row in body["results"]}
        self.assertEqual(session_ids, {"session-a", "session-b"})

    def test_list_dedupes_to_latest_per_session(self) -> None:
        first = self._make_summary("session-a", model_used="gpt-old")
        first.created_at = datetime(2026, 1, 1, tzinfo=UTC)
        first.save(update_fields=["created_at"])
        self._make_summary("session-a", model_used="gpt-new")

        response = self.client.get(self._url())

        self.assertEqual(response.status_code, 200)
        results = response.json()["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["model_used"], "gpt-new")

    def test_list_returns_lightweight_shape(self) -> None:
        self._make_summary(
            "session-a",
            exception_event_ids=["evt-1", "evt-2"],
            visual_confirmation=True,
        )

        response = self.client.get(self._url())

        self.assertEqual(response.status_code, 200)
        row = response.json()["results"][0]
        self.assertEqual(row["session_id"], "session-a")
        self.assertEqual(row["distinct_id"], "user-1")
        self.assertEqual(row["exception_count"], 2)
        self.assertTrue(row["has_exceptions"])
        self.assertTrue(row["visual_confirmation"])
        self.assertEqual(row["model_used"], "gpt-4o")
        self.assertIsNone(row["extra_summary_context"])
        self.assertEqual(row["session_outcome"]["success"], True)
        # The full summary JSON must not leak into the list shape.
        self.assertNotIn("summary", row)
        self.assertNotIn("exception_event_ids", row)

    def test_list_filter_session_ids_csv(self) -> None:
        self._make_summary("session-a")
        self._make_summary("session-b")
        self._make_summary("session-c")

        response = self.client.get(self._url(), {"session_ids": "session-a,session-c"})

        self.assertEqual(response.status_code, 200)
        session_ids = {row["session_id"] for row in response.json()["results"]}
        self.assertEqual(session_ids, {"session-a", "session-c"})

    def test_list_filter_outcome_success(self) -> None:
        self._make_summary("session-success", success=True)
        self._make_summary("session-failure", success=False)
        self._make_summary("session-unknown", success=None)

        response = self.client.get(self._url(), {"outcome": "success"})
        ids = {row["session_id"] for row in response.json()["results"]}
        self.assertEqual(ids, {"session-success"})

        response = self.client.get(self._url(), {"outcome": "failure"})
        ids = {row["session_id"] for row in response.json()["results"]}
        self.assertEqual(ids, {"session-failure"})

    def test_list_filter_has_exceptions(self) -> None:
        self._make_summary("session-with-exc", exception_event_ids=["evt-1"])
        self._make_summary("session-no-exc", exception_event_ids=[])

        response = self.client.get(self._url(), {"has_exceptions": "true"})
        ids = {row["session_id"] for row in response.json()["results"]}
        self.assertEqual(ids, {"session-with-exc"})

        response = self.client.get(self._url(), {"has_exceptions": "false"})
        ids = {row["session_id"] for row in response.json()["results"]}
        self.assertEqual(ids, {"session-no-exc"})

    def test_list_filter_has_visual_confirmation(self) -> None:
        self._make_summary("session-video", visual_confirmation=True)
        self._make_summary("session-event-only", visual_confirmation=False)

        response = self.client.get(self._url(), {"has_visual_confirmation": "true"})
        ids = {row["session_id"] for row in response.json()["results"]}
        self.assertEqual(ids, {"session-video"})

    def test_list_filter_distinct_id(self) -> None:
        self._make_summary("session-a", distinct_id="alice")
        self._make_summary("session-b", distinct_id="bob")

        response = self.client.get(self._url(), {"distinct_id": "alice"})
        ids = {row["session_id"] for row in response.json()["results"]}
        self.assertEqual(ids, {"session-a"})

    def test_list_date_bounds_are_inclusive(self) -> None:
        boundary = self._make_summary("session-boundary")
        boundary.created_at = datetime(2026, 3, 1, tzinfo=UTC)
        boundary.save(update_fields=["created_at"])
        earlier = self._make_summary("session-earlier")
        earlier.created_at = datetime(2026, 2, 1, tzinfo=UTC)
        earlier.save(update_fields=["created_at"])

        # date_from equal to the boundary timestamp must include that row (inclusive lower bound).
        response = self.client.get(self._url(), {"date_from": "2026-03-01"})
        ids = {row["session_id"] for row in response.json()["results"]}
        self.assertIn("session-boundary", ids)
        self.assertNotIn("session-earlier", ids)

        # date_to equal to the boundary timestamp must include that row (inclusive upper bound).
        response = self.client.get(self._url(), {"date_to": "2026-03-01"})
        ids = {row["session_id"] for row in response.json()["results"]}
        self.assertIn("session-boundary", ids)
        self.assertIn("session-earlier", ids)

    def test_list_orders_by_allowed_field(self) -> None:
        short = self._make_summary("session-short", session_duration=10)
        long = self._make_summary("session-long", session_duration=999)

        response = self.client.get(self._url(), {"order": "-session_duration"})

        self.assertEqual(response.status_code, 200)
        ordered_ids = [row["session_id"] for row in response.json()["results"]]
        self.assertEqual(ordered_ids, [long.session_id, short.session_id])

    def test_list_rejects_unknown_order_field(self) -> None:
        self._make_summary("session-a")

        response = self.client.get(self._url(), {"order": "created_by__email"})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["attr"], "order")

    def test_list_rejects_invalid_created_by(self) -> None:
        self._make_summary("session-a")
        response = self.client.get(self._url(), {"created_by": "not-a-uuid"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["attr"], "created_by")

    def test_list_rejects_unparseable_date(self) -> None:
        self._make_summary("session-a")
        response = self.client.get(self._url(), {"date_from": "yesterday"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["attr"], "date_from")

    def test_list_accepts_relative_date_shorthand(self) -> None:
        self._make_summary("session-a")
        response = self.client.get(self._url(), {"date_from": "-30d"})
        self.assertEqual(response.status_code, 200)

    def test_list_state_filter_reflects_latest_summary(self) -> None:
        # A session whose older summary failed but latest succeeded must NOT appear under
        # outcome=failure (list stays consistent with what retrieve returns — the latest).
        older = self._make_summary("sess-flip", success=False)
        older.created_at = datetime(2026, 1, 1, tzinfo=UTC)
        older.save(update_fields=["created_at"])
        self._make_summary("sess-flip", success=True)

        failure = self.client.get(self._url(), {"outcome": "failure"})
        self.assertEqual([row["session_id"] for row in failure.json()["results"]], [])

        success = self.client.get(self._url(), {"outcome": "success"})
        self.assertEqual({row["session_id"] for row in success.json()["results"]}, {"sess-flip"})

    def test_list_and_retrieve_exclude_deleted_recordings(self) -> None:
        self._make_summary("live-rec")
        self._make_summary("deleted-rec")
        SessionRecording.objects.create(team=self.team, session_id="deleted-rec", deleted=True)

        ids = {row["session_id"] for row in self.client.get(self._url()).json()["results"]}
        self.assertIn("live-rec", ids)
        self.assertNotIn("deleted-rec", ids)

        self.assertEqual(self.client.get(self._url("deleted-rec")).status_code, 404)

    def test_retrieve_returns_full_summary(self) -> None:
        self._make_summary(
            "session-a",
            exception_event_ids=["evt-1"],
            visual_confirmation=True,
        )

        response = self.client.get(self._url("session-a"))

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["session_id"], "session-a")
        self.assertIn("segments", body["summary"])
        self.assertIn("key_actions", body["summary"])
        self.assertIn("session_outcome", body["summary"])
        self.assertEqual(body["exception_event_ids"], ["evt-1"])
        self.assertIsNone(body["extra_summary_context"])
        self.assertEqual(body["run_metadata"]["model_used"], "gpt-4o")
        self.assertEqual(body["run_metadata"]["visual_confirmation"], True)

    def test_retrieve_returns_default_context_over_newer_focused_summary(self) -> None:
        # The retrieve path matches `get_summary(..., extra_summary_context=None)`: a focused
        # (`focus_area`) summary must not shadow the default one, even if it's newer.
        default = self._make_summary("sess-ctx", model_used="default-model")
        default.created_at = datetime(2026, 1, 1, tzinfo=UTC)
        default.save(update_fields=["created_at"])
        self._make_summary("sess-ctx", model_used="focused-model", focus_area="checkout")

        response = self.client.get(self._url("sess-ctx"))

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["extra_summary_context"])
        self.assertEqual(response.json()["run_metadata"]["model_used"], "default-model")

    def test_retrieve_404_when_only_focused_context_exists(self) -> None:
        self._make_summary("sess-focused-only", focus_area="checkout")
        response = self.client.get(self._url("sess-focused-only"))
        self.assertEqual(response.status_code, 404)

    def test_list_only_returns_default_context_summaries(self) -> None:
        # List keys on the default (null-context) summary, like retrieve — a focused-only session
        # does not appear, and a session with both shows its default row (even if focused is newer).
        self._make_summary("sess-default-only")
        self._make_summary("sess-focused-only", focus_area="checkout")
        default = self._make_summary("sess-both")
        default.created_at = datetime(2026, 1, 1, tzinfo=UTC)
        default.save(update_fields=["created_at"])
        self._make_summary("sess-both", focus_area="checkout")

        results = {row["session_id"]: row for row in self.client.get(self._url()).json()["results"]}
        self.assertIn("sess-default-only", results)
        self.assertNotIn("sess-focused-only", results)
        self.assertIsNone(results["sess-both"]["extra_summary_context"])

    def test_retrieve_returns_latest_summary_when_multiple_exist(self) -> None:
        older = self._make_summary("session-a", model_used="gpt-old")
        older.created_at = datetime(2026, 1, 1, tzinfo=UTC)
        older.save(update_fields=["created_at"])
        self._make_summary("session-a", model_used="gpt-new")

        response = self.client.get(self._url("session-a"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["run_metadata"]["model_used"], "gpt-new")

    def test_retrieve_returns_404_when_missing(self) -> None:
        response = self.client.get(self._url("nonexistent-session"))
        self.assertEqual(response.status_code, 404)

    def test_retrieve_other_team_summary_is_404(self) -> None:
        other_team = Organization.objects.bootstrap(None)[2]
        self._make_summary("cross-team", team=other_team)

        response = self.client.get(self._url("cross-team"))
        self.assertEqual(response.status_code, 404)

    def test_list_unauthenticated(self) -> None:
        self.client.logout()
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 401)

    def test_create_is_not_allowed(self) -> None:
        response = self.client.post(self._url(), {"session_id": "x"}, format="json")
        self.assertIn(response.status_code, (403, 405))

    def test_delete_is_not_allowed(self) -> None:
        self._make_summary("session-a")
        response = self.client.delete(self._url("session-a"))
        self.assertIn(response.status_code, (403, 405))

    def test_run_metadata_fields_handle_none(self) -> None:
        # Older rows may have written before run_metadata was added; the API should not crash on them.
        SingleSessionSummary.objects.create(
            team=self.team,
            session_id="legacy-session",
            summary=get_mock_enriched_llm_json_response("legacy-session"),
            exception_event_ids=[],
            run_metadata=None,
            session_start_time=datetime(2026, 1, 1, tzinfo=UTC),
        )

        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 200)
        row = next(r for r in response.json()["results"] if r["session_id"] == "legacy-session")
        self.assertIsNone(row["model_used"])
        self.assertFalse(row["visual_confirmation"])

        # Retrieve serializes the null run_metadata without crashing (schema marks it nullable).
        retrieve = self.client.get(self._url("legacy-session"))
        self.assertEqual(retrieve.status_code, 200)
        self.assertIsNone(retrieve.json()["run_metadata"])

    def test_dataclass_round_trip_via_manager(self) -> None:
        # Sanity check that the serializer produces what the manager writes via the production code path.
        summary_data = get_mock_enriched_llm_json_response("session-a")
        serializer = SessionSummarySerializer(data=summary_data)
        serializer.is_valid(raise_exception=True)
        SingleSessionSummary.objects.add_summary(
            team_id=self.team.id,
            session_id="session-a",
            summary=serializer,
            exception_event_ids=["evt-1"],
            extra_summary_context=None,
            run_metadata=SessionSummaryRunMeta(model_used="gpt-4o", visual_confirmation=False),
            created_by=self.user,
        )

        response = self.client.get(self._url("session-a"))

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["session_id"], "session-a")
        self.assertIn("segments", body["summary"])
        self.assertIsNone(body["extra_summary_context"])


@pytest.mark.ee
class TestSingleSessionSummaryViewSetAccessControl(APIBaseTest):
    """A summary's access must follow the underlying recording's, even though `SingleSessionSummary`
    is not itself a mapped access-control resource. Without per-recording gating, a user with object-level
    access to one recording could read summaries for every recording in the team."""

    def _url(self, session_id: str | None = None) -> str:
        base = f"/api/projects/{self.team.id}/single_session_summaries/"
        return base if session_id is None else f"{base}{session_id}/"

    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()

        self.viewer_user = User.objects.create_and_join(self.organization, "viewer@posthog.com", "testtest")

        # Two recordings + their persisted summaries, created by the admin (not the viewer).
        self.recording_allowed = SessionRecording.objects.create(
            team=self.team, session_id="rec-allowed", distinct_id="u1", deleted=False
        )
        self.recording_denied = SessionRecording.objects.create(
            team=self.team, session_id="rec-denied", distinct_id="u2", deleted=False
        )
        for session_id in ("rec-allowed", "rec-denied"):
            SingleSessionSummary.objects.create(
                team=self.team,
                session_id=session_id,
                summary=copy.deepcopy(get_mock_enriched_llm_json_response(session_id)),
                exception_event_ids=[],
                run_metadata={"model_used": "gpt-4o", "visual_confirmation": False},
                session_start_time=datetime(2026, 1, 1, tzinfo=UTC),
                created_by=self.user,
            )

        # Viewer can see only `rec-allowed`: object-level grant + resource-level "none".
        membership = OrganizationMembership.objects.get(user=self.viewer_user, organization=self.organization)
        AccessControl.objects.create(
            team=self.team,
            resource="session_recording",
            resource_id=str(self.recording_allowed.id),
            access_level="viewer",
            organization_member=membership,
        )
        AccessControl.objects.create(
            team=self.team,
            resource="session_recording",
            resource_id=None,
            access_level="none",
            organization_member=membership,
        )
        self.client.force_login(self.viewer_user)

    def test_list_only_returns_summaries_for_accessible_recordings(self) -> None:
        response = self.client.get(self._url())

        self.assertEqual(response.status_code, 200)
        session_ids = {row["session_id"] for row in response.json()["results"]}
        self.assertEqual(session_ids, {"rec-allowed"})

    def test_retrieve_accessible_recording_summary_succeeds(self) -> None:
        response = self.client.get(self._url("rec-allowed"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["session_id"], "rec-allowed")

    def test_retrieve_inaccessible_recording_summary_is_forbidden(self) -> None:
        response = self.client.get(self._url("rec-denied"))
        self.assertEqual(response.status_code, 403)

    def test_full_recording_access_sees_all_summaries(self) -> None:
        # A user with team-wide viewer access takes the fast path (no per-recording filtering).
        membership = OrganizationMembership.objects.get(user=self.viewer_user, organization=self.organization)
        AccessControl.objects.filter(team=self.team, organization_member=membership, resource_id=None).update(
            access_level="viewer"
        )

        response = self.client.get(self._url())

        self.assertEqual(response.status_code, 200)
        session_ids = {row["session_id"] for row in response.json()["results"]}
        self.assertEqual(session_ids, {"rec-allowed", "rec-denied"})

    def test_list_honors_object_level_deny_with_team_access(self) -> None:
        # Team-wide viewer access, but one recording explicitly denied: the list must exclude it
        # (the fast path can't blanket-skip filtering when per-recording denies exist).
        membership = OrganizationMembership.objects.get(user=self.viewer_user, organization=self.organization)
        AccessControl.objects.filter(team=self.team, organization_member=membership, resource_id=None).update(
            access_level="viewer"
        )
        AccessControl.objects.create(
            team=self.team,
            resource="session_recording",
            resource_id=str(self.recording_denied.id),
            access_level="none",
            organization_member=membership,
        )

        response = self.client.get(self._url())

        self.assertEqual(response.status_code, 200)
        session_ids = {row["session_id"] for row in response.json()["results"]}
        self.assertEqual(session_ids, {"rec-allowed"})
