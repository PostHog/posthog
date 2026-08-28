from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.clickhouse.query_tagging import Feature, get_query_tags
from posthog.constants import AvailableFeature
from posthog.models.ai_events.test_util import bulk_create_ai_events
from posthog.models.organization import OrganizationMembership
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.team import Team
from posthog.models.user import User
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.access_control.backend.models.access_control import AccessControl
from products.ai_observability.backend.instrumentation_checklist.grading import VOLUME_FLOOR, ChecklistStats
from products.ai_observability.backend.instrumentation_checklist.stats import WINDOW_DAYS
from products.ai_observability.backend.models.instrumentation_checklist import AIObservabilityChecklistItemState
from products.ai_observability.backend.models.review_queues import ReviewQueue

CHECK_FIELDS = {"key", "status", "title", "detail", "docs_url", "stats"}


def endpoint(team_id: int, suffix: str = "") -> str:
    return f"/api/projects/{team_id}/ai_observability/instrumentation_checklist/{suffix}"


def check(body: dict[str, Any], key: str) -> dict[str, Any]:
    return next(item for item in body["checks"] if item["key"] == key)


def generation(
    team: Team,
    index: int,
    *,
    distinct_id: str | None = None,
    properties: dict[str, str] | None = None,
) -> dict[str, Any]:
    trace_id = f"trace-{index}"
    return {
        "event": "$ai_generation",
        # An unset distinct_id mirrors the un-instrumented shape: the SDK falls back to the trace id.
        "distinct_id": distinct_id or trace_id,
        "team": team,
        "timestamp": datetime.now(UTC) - timedelta(days=1),
        "properties": {"$ai_trace_id": trace_id, **(properties or {})},
    }


class TestInstrumentationChecklist(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        # Exactly enough generations to clear the volume floor, one of them instrumented for
        # sessions and user identity so the payload carries both an `ok` and a `warning`.
        bulk_create_ai_events(
            [
                *(generation(self.team, index) for index in range(VOLUME_FLOOR - 1)),
                generation(
                    self.team,
                    VOLUME_FLOOR - 1,
                    distinct_id="user-42",
                    properties={"$ai_session_id": "session-1"},
                ),
            ]
        )

    @parameterized.expand([("list", ""), ("dismiss", "dismiss/"), ("restore", "restore/")])
    def test_the_clickhouse_read_carries_a_feature_tag(self, _name: str, suffix: str) -> None:
        # sync_execute rejects a query missing the feature tag, but only when DEBUG and not TEST,
        # so asserting on the response status would pass here while a browser gets a 500. Read the
        # tag at the point the query would run instead.
        seen: list[Feature | None] = []

        def record(team: Team) -> ChecklistStats:
            seen.append(get_query_tags().feature)
            return ChecklistStats(
                generations=0,
                events_with_session=0,
                events_declining_session=0,
                generations_with_tool_calls=0,
                generations_with_tools_declared=0,
                sdk_generations=0,
                sdk_generations_identified=0,
                spans=0,
                events_with_parent=0,
                total_events=0,
            )

        with patch(
            "products.ai_observability.backend.api.instrumentation_checklist.fetch_checklist_stats",
            side_effect=record,
        ):
            if suffix:
                response = self.client.post(endpoint(self.team.pk, suffix), {"check": "sessions"}, format="json")
            else:
                response = self.client.get(endpoint(self.team.pk))

        # Asserting the status too, so a stub that raises cannot leave the tag recorded and the
        # request failing while this still passes.
        assert response.status_code == status.HTTP_200_OK, response.content
        assert seen == [Feature.INSTRUMENTATION_CHECKLIST]

    def test_get_returns_every_check_graded_over_the_teams_events(self) -> None:
        response = self.client.get(endpoint(self.team.pk))

        assert response.status_code == status.HTTP_200_OK, response.content
        body = response.json()
        assert body["window_days"] == WINDOW_DAYS
        assert [(item["key"], item["status"]) for item in body["checks"]] == [
            ("sessions", "ok"),
            ("tool_calls", "warning"),
            ("user_identity", "ok"),
            ("trace_structure", "warning"),
        ]
        assert all(set(item) == CHECK_FIELDS for item in body["checks"])
        assert check(body, "sessions")["stats"] == {
            "generations": VOLUME_FLOOR,
            "events_with_session": 1,
            "events_declining_session": 0,
        }

    def test_dismissal_mutes_a_check_until_it_is_restored(self) -> None:
        dismissed = self.client.post(endpoint(self.team.pk, "dismiss/"), {"check": "tool_calls"})

        assert dismissed.status_code == status.HTTP_200_OK, dismissed.content
        assert check(dismissed.json(), "tool_calls")["status"] == "dismissed"
        # The muted row keeps the sentence its counts earned, so it still says what "Recheck" would re-evaluate.
        assert "No tool calls recorded" in check(dismissed.json(), "tool_calls")["detail"]
        assert check(self.client.get(endpoint(self.team.pk)).json(), "tool_calls")["status"] == "dismissed"
        state = AIObservabilityChecklistItemState.objects.for_team(self.team.pk).get(check_key="tool_calls")
        assert state.updated_by == self.user

        repeated = self.client.post(endpoint(self.team.pk, "dismiss/"), {"check": "tool_calls"})
        assert repeated.status_code == status.HTTP_200_OK, repeated.content

        restored = self.client.post(endpoint(self.team.pk, "restore/"), {"check": "tool_calls"})
        assert restored.status_code == status.HTTP_200_OK, restored.content
        assert check(restored.json(), "tool_calls")["status"] == "warning"
        assert not AIObservabilityChecklistItemState.objects.for_team(self.team.pk).exists()

    @parameterized.expand([("dismiss",), ("restore",)])
    def test_an_unknown_check_is_rejected_rather_than_stored(self, action: str) -> None:
        response = self.client.post(endpoint(self.team.pk, f"{action}/"), {"check": "wibble"})

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert not AIObservabilityChecklistItemState.objects.for_team(self.team.pk).exists()

    def test_a_dismissal_does_not_reach_another_project(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other project")

        dismissed = self.client.post(endpoint(other_team.pk, "dismiss/"), {"check": "tool_calls"})
        assert dismissed.status_code == status.HTTP_200_OK, dismissed.content

        body = self.client.get(endpoint(self.team.pk)).json()
        assert check(body, "tool_calls")["status"] == "warning"

    def test_a_dismissal_from_a_child_environment_is_durable_and_repeatable(self) -> None:
        # RootTeamMixin.save() rewrites the row onto the parent team, so a lookup keyed on the
        # environment's own id would miss the row it just wrote: the read shows the check
        # undismissed, and the second dismissal violates the partial unique constraint.
        environment = Team.objects.create(
            organization=self.organization, project=self.project, parent_team=self.team, name="Staging"
        )

        first = self.client.post(endpoint(environment.pk, "dismiss/"), {"check": "tool_calls"})
        assert first.status_code == status.HTTP_200_OK, first.content
        assert check(self.client.get(endpoint(environment.pk)).json(), "tool_calls")["status"] == "dismissed"

        second = self.client.post(endpoint(environment.pk, "dismiss/"), {"check": "tool_calls"})
        assert second.status_code == status.HTTP_200_OK, second.content
        assert check(second.json(), "tool_calls")["status"] == "dismissed"


class TestInstrumentationChecklistResourceLevelAccess(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        queue = ReviewQueue.objects.create(team=self.team, name="Support queue", created_by=self.user)
        member = User.objects.create_and_join(self.organization, "queue-reviewer@posthog.com", "testtest")
        membership = OrganizationMembership.objects.get(user=member, organization=self.organization)
        AccessControl.objects.create(
            team=self.team,
            resource="llm_analytics",
            access_level="none",
            organization_member=membership,
        )
        # Granting editor rather than viewer on the queue clears has_any_specific_access_for_resource
        # at both the viewer level the read needs and the editor level the writes need, so all three
        # actions reach the requires_resource_level_access branch instead of being turned away for
        # the wrong reason.
        AccessControl.objects.create(
            team=self.team,
            resource="llm_analytics",
            resource_id=str(queue.id),
            access_level="editor",
            organization_member=membership,
        )
        self.client.force_login(member)

    @parameterized.expand([("list", ""), ("dismiss", "dismiss/"), ("restore", "restore/")])
    def test_a_grant_on_one_object_does_not_reach_the_project_wide_checklist(self, _name: str, suffix: str) -> None:
        if suffix:
            response = self.client.post(endpoint(self.team.pk, suffix), {"check": "tool_calls"})
        else:
            response = self.client.get(endpoint(self.team.pk))

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
        assert not AIObservabilityChecklistItemState.objects.for_team(self.team.pk).exists()


class TestInstrumentationChecklistApiKeyAccess(ClickhouseTestMixin, APIBaseTest):
    @parameterized.expand([("dismiss",), ("restore",)])
    def test_a_personal_api_key_can_reach_the_custom_actions(self, action: str) -> None:
        raw_key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="checklist",
            user=self.user,
            secure_value=hash_key_value(raw_key),
            scopes=["llm_analytics:write"],
        )
        # force_login skips APIScopePermission entirely, so only a real token exercises the scope wiring.
        self.client.logout()

        response = self.client.post(
            endpoint(self.team.pk, f"{action}/"),
            {"check": "tool_calls"},
            headers={"authorization": f"Bearer {raw_key}"},
        )

        assert response.status_code == status.HTTP_200_OK, response.content
