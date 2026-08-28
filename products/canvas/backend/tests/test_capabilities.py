from unittest import TestCase

from parameterized import parameterized

from products.canvas.backend.capabilities import capability_widening

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
        "agentRequests": True,
    },
    "network": {"origins": ["https://api.example.com"]},
}
NARROWER = {
    "posthog": {"insights": [], "captureEvents": [], "inlineQueries": False, "agentRequests": False},
    "network": {"origins": []},
}


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

    def test_inline_queries_already_enabled_is_not_a_widening(self):
        enabled = {"posthog": {"inlineQueries": True}}
        assert capability_widening(enabled, enabled).widens is False
