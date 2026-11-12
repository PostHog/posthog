"""The feature flag that gates suggestions per organization, and the tunables its payload carries."""

import json
from typing import Any

from django.conf import settings

import structlog
import posthoganalytics

from posthog.dataclasses import frozen

logger = structlog.get_logger(__name__)

FEATURE_FLAG = "llm-analytics-eval-suggestions"


@frozen
class SuggestionSettings:
    jeeves: bool = True
    llm_drafting: bool = False
    llm_budget_usd_per_run: float = 20.0
    max_teams_per_run: int = 2000
    max_concurrent_teams: int = 4


def parse_settings(payload: Any) -> SuggestionSettings:
    """Each value falls back to its default when it is missing or has the wrong type, so a typo in the
    payload switches off nothing it did not name."""
    defaults = SuggestionSettings()
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            payload = None
    data: dict[str, Any] = payload if isinstance(payload, dict) else {}
    raw_stages = data.get("stages")
    stages: dict[str, Any] = raw_stages if isinstance(raw_stages, dict) else {}

    def flag(name: str, default: bool) -> bool:
        value = stages.get(name)
        return value if isinstance(value, bool) else default

    def positive(name: str, default: float) -> float:
        value = data.get(name)
        return value if isinstance(value, int | float) and not isinstance(value, bool) and value > 0 else default

    def count(name: str, default: int) -> int:
        value = data.get(name)
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 1 else default

    return SuggestionSettings(
        jeeves=flag("jeeves", defaults.jeeves),
        llm_drafting=flag("llm_drafting", defaults.llm_drafting),
        llm_budget_usd_per_run=float(positive("llm_budget_usd_per_run", defaults.llm_budget_usd_per_run)),
        max_teams_per_run=count("max_teams_per_run", defaults.max_teams_per_run),
        max_concurrent_teams=count("max_concurrent_teams", defaults.max_concurrent_teams),
    )


def load_settings() -> SuggestionSettings:
    try:
        # match_value reads the payload attached to the enabled value without evaluating the rollout. Local
        # evaluation only: workers poll flag definitions, and a remote lookup can hang a worker thread for minutes.
        payload = posthoganalytics.get_feature_flag_payload(
            FEATURE_FLAG,
            "llma-eval-suggestions",
            match_value=True,
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
    except Exception:
        logger.warning("eval_suggestions_settings_unreadable", exc_info=True)
        payload = None
    return parse_settings(payload)


def is_enabled_for_organization(organization_id: str) -> bool:
    if settings.DEBUG or settings.E2E_TESTING:
        return True
    return (
        posthoganalytics.feature_enabled(
            FEATURE_FLAG,
            organization_id,
            groups={"organization": organization_id},
            group_properties={"organization": {"id": organization_id}},
            # The weekly plan checks every visited organization in turn, so a remote lookup per organization
            # could use up its deadline. Without local definitions the organization stays off.
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
        is True
    )
