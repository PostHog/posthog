from unittest.mock import patch

from parameterized import parameterized

from products.ai_observability.backend.logic.eval_suggestions import config
from products.ai_observability.backend.logic.eval_suggestions.config import SuggestionSettings, parse_settings


@parameterized.expand(
    [
        ("missing", None, SuggestionSettings()),
        (
            "json_string",
            '{"stages": {"jeeves": false}, "max_concurrent_teams": 8}',
            SuggestionSettings(jeeves=False, max_concurrent_teams=8),
        ),
        (
            "wrong_types_fall_back_one_by_one",
            {"stages": {"llm_drafting": "yes"}, "llm_budget_usd_per_run": -5, "max_teams_per_run": 10},
            SuggestionSettings(max_teams_per_run=10),
        ),
        ("fractional_counts_fall_back", {"max_concurrent_teams": 0.5, "max_teams_per_run": 0.9}, SuggestionSettings()),
    ]
)
def test_flag_payload_settings(_name: str, payload: object, expected: SuggestionSettings) -> None:
    assert parse_settings(payload) == expected


@parameterized.expand(
    [
        ("visible", {config.FEATURE_FLAG}, True, True),
        ("shadow_only", {config.SHADOW_FEATURE_FLAG}, False, True),
        ("neither", set(), False, False),
    ]
)
def test_a_shadow_organization_runs_without_seeing_suggestions(
    _name: str, flags_on: set[str], sees: bool, runs: bool
) -> None:
    with patch.object(config.posthoganalytics, "feature_enabled", side_effect=lambda flag, *_, **__: flag in flags_on):
        assert (config.is_enabled_for_organization("org"), config.runs_for_organization("org")) == (sees, runs)
