from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models import Team

from products.cloud_agents.backend.facade import api
from products.cloud_agents.backend.facade.contracts import (
    CloudAgentsError,
    ConcurrencyLimited,
    CreateRateLimited,
    PresetNotFound,
    RepositoryRef,
    RunDone,
    RunNotFound,
    UsageLimited,
)
from products.cloud_agents.backend.models import CloudAgentPreset
from products.cloud_agents.backend.presentation.errors import to_api_exception
from products.cloud_agents.backend.tests.base import caller_for


class TestPresetLookup(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.preset = CloudAgentPreset.objects.create(team=self.team, name="Backend Fixes")

    @parameterized.expand(
        [
            ("exact_name", "Backend Fixes"),
            ("other_case", "backend fixes"),
            ("padded", "  BACKEND FIXES "),
        ]
    )
    def test_lookup_by_name(self, _name: str, ref: str) -> None:
        assert api.get_preset_by_ref(self.team.id, ref).id == self.preset.id

    def test_lookup_by_id(self) -> None:
        assert api.get_preset_by_ref(self.team.id, str(self.preset.id)).name == "Backend Fixes"

    @parameterized.expand([("unknown_name",), ("deleted",), ("other_team_by_name",), ("other_team_by_id",)])
    def test_lookup_misses(self, case: str) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other team")
        theirs = CloudAgentPreset.all_teams.create(team=other_team, name="Theirs")
        ref = {
            "unknown_name": "Frontend",
            "deleted": "Backend Fixes",
            "other_team_by_name": "Theirs",
            "other_team_by_id": str(theirs.id),
        }[case]
        if case == "deleted":
            api.delete_preset(self.team.id, self.preset.id, caller_for(self.user))
        with self.assertRaises(PresetNotFound):
            api.get_preset_by_ref(self.team.id, ref)


class TestAnalytics(BaseTest):
    def test_settings_event_carries_field_names_and_no_values(self) -> None:
        with patch("products.cloud_agents.backend.logic.settings.capture_event") as capture_event:
            api.update_team_settings(
                self.team.id,
                {"instructions": "Never touch billing", "repositories": [RepositoryRef(name="acme/app")]},
                caller_for(self.user),
            )
        event, _caller, team_id, properties = capture_event.call_args.args
        assert (event, team_id) == ("cloud_agents_settings_updated", self.team.id)
        assert properties == {"changed_fields": ["instructions", "repositories"]}

    def test_no_event_when_nothing_changes(self) -> None:
        with patch("products.cloud_agents.backend.logic.settings.capture_event") as capture_event:
            api.update_team_settings(self.team.id, {}, caller_for(self.user))
        capture_event.assert_not_called()


class TestErrorMapping(SimpleTestCase):
    @parameterized.expand(
        [
            ("concurrency", ConcurrencyLimited(limit=5, active=5), 429, "concurrency_limited", 30),
            ("create_rate", CreateRateLimited(retry_after=42), 429, "create_rate_limited", 42),
            ("usage", UsageLimited(), 429, "usage_limited", None),
            ("not_found", RunNotFound(), 404, "run_not_found", None),
            ("done", RunDone(), 409, "run_done", None),
        ]
    )
    def test_status_code_and_retry_after(
        self, _name: str, error: CloudAgentsError, status_code: int, code: str, retry_after: int | None
    ) -> None:
        api_error = to_api_exception(error)
        assert api_error.status_code == status_code
        assert api_error.get_codes() == code
        assert getattr(api_error, "wait", None) == retry_after
