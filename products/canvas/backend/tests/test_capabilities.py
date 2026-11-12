from unittest import TestCase

from parameterized import parameterized

from posthog.models.user import User

from products.canvas.backend.capabilities import ConnectorGrant, capability_widening
from products.canvas.backend.facade.contracts import CanvasCapabilityWideningDenied
from products.canvas.backend.logic.capability_policy import assert_may_set_capabilities
from products.canvas.backend.models import Canvas

BASE = {
    "posthog": {
        "insights": ["abc"],
        "captureEvents": ["clicked"],
        "inlineQueries": False,
        "agentRequests": False,
    },
    "network": {"origins": []},
}
WIDER = {
    "posthog": {
        "insights": ["abc", "def"],
        "captureEvents": ["clicked"],
        "inlineQueries": True,
        "state": ["user"],
        "actions": ["tasks.create"],
        "tools": ["feature-flag-enable"],
        "agentRequests": True,
    },
    "network": {"origins": ["https://api.example.com"]},
    "connectors": [
        {"provider": "github", "tools": ["list_pull_requests", "search_issues"]},
        {"provider": "mcp:mcp.example.com", "tools": ["list_events"]},
    ],
}
NARROWER = {
    "posthog": {"insights": [], "captureEvents": [], "inlineQueries": False, "agentRequests": False},
    "network": {"origins": []},
}


STANDARD = Canvas.SOURCE_POLICY_STANDARD


class TestCapabilityWidening(TestCase):
    @parameterized.expand(
        [
            ("identical", BASE, BASE, False),
            ("narrowing_only", BASE, NARROWER, False),
            ("unknown_baseline_flags_everything", None, BASE, True),
            ("empty_manifests", {}, {}, False),
        ]
    )
    def test_widens_flag(self, _name, before, after, expected):
        assert capability_widening(before, after).widens is expected

    def test_reports_each_added_capability(self):
        widening = capability_widening(BASE, WIDER)
        assert widening.widens is True
        assert widening.insights_added == ["def"]
        assert widening.capture_events_added == []
        assert widening.inline_queries_enabled is True
        assert widening.agent_requests_enabled is True
        assert widening.network_origins_added == ["https://api.example.com"]
        assert widening.state_scopes_added == ["user"]
        assert widening.actions_added == ["tasks.create"]
        assert widening.tools_added == ["feature-flag-enable"]
        assert widening.connectors_added == [
            ConnectorGrant(provider="github", tools=["list_pull_requests", "search_issues"]),
            ConnectorGrant(provider="mcp:mcp.example.com", tools=["list_events"]),
        ]

    def test_only_new_connector_tools_count_as_widening(self):
        before = {"connectors": [{"provider": "github", "tools": ["list_pull_requests"]}]}
        after = {"connectors": [{"provider": "github", "tools": ["search_issues", "list_pull_requests"]}]}
        widening = capability_widening(before, after)
        assert widening.connectors_added == [ConnectorGrant(provider="github", tools=["search_issues"])]
        assert capability_widening(after, before).widens is False

    def test_inline_queries_already_enabled_is_not_a_widening(self):
        enabled = {"posthog": {"inlineQueries": True}}
        assert capability_widening(enabled, enabled).widens is False


class TestAssertMaySetCapabilities(TestCase):
    @parameterized.expand(
        [
            ("creator_widens", 1, 1, BASE, WIDER, False, STANDARD),
            ("non_creator_widens", 1, 2, BASE, WIDER, True, STANDARD),
            ("non_creator_narrows", 1, 2, WIDER, NARROWER, False, STANDARD),
            ("non_creator_keeps", 1, 2, WIDER, WIDER, False, STANDARD),
            ("creator_gone", None, 1, BASE, WIDER, True, STANDARD),
            ("no_acting_user", 1, None, BASE, WIDER, True, STANDARD),
            ("missing_baseline_counts_as_empty", 1, 2, None, BASE, True, STANDARD),
            ("missing_baseline_and_empty_after", 1, 2, None, {}, False, STANDARD),
            ("unknown_target_needs_the_creator", 1, 2, BASE, None, True, STANDARD),
            ("unknown_target_for_the_creator", 1, 1, BASE, None, False, STANDARD),
            ("notebook_widget_is_exempt", 1, 2, BASE, WIDER, False, Canvas.SOURCE_POLICY_NOTEBOOK_WIDGET),
        ]
    )
    def test_only_the_creator_may_widen(
        self,
        _name: str,
        creator_id: int | None,
        user_id: int | None,
        before: dict | None,
        after: dict | None,
        denied: bool,
        source_policy: str,
    ) -> None:
        canvas = Canvas(created_by_id=creator_id, source_policy=source_policy)
        user = User(id=user_id) if user_id is not None else None
        if denied:
            with self.assertRaises(CanvasCapabilityWideningDenied):
                assert_may_set_capabilities(canvas, user, before, after)
        else:
            assert_may_set_capabilities(canvas, user, before, after)
