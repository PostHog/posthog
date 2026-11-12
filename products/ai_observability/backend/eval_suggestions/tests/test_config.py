from parameterized import parameterized

from products.ai_observability.backend.eval_suggestions.config import SuggestionSettings, parse_settings


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
