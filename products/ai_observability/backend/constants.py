from datetime import UTC, datetime

from django.conf import settings

# Cutoff for the trial-eval deprecation: grandfathered teams keep PostHog-funded inference until
# this date. Extendable without a deploy via the env var (see posthog/settings/base_variables.py).
DEFAULT_TRIAL_EVAL_DEPRECATION_DATE = datetime(2026, 7, 17, tzinfo=UTC)


def trial_eval_deprecation_date() -> datetime:
    override = settings.AI_OBSERVABILITY_TRIAL_EVAL_DEPRECATION_DATE
    if override:
        parsed = datetime.fromisoformat(override)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return DEFAULT_TRIAL_EVAL_DEPRECATION_DATE
