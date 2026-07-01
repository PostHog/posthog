from datetime import UTC, datetime

from django.conf import settings

# Trial evaluations are being deprecated. Teams already mid-trial keep PostHog-funded eval/tagger
# inference until this cutoff; after it (and for teams that never started or already exhausted the
# trial) every team is terminal and must bring its own provider key. Overridable via settings so the
# window can be extended without a code change if needed.
DEFAULT_TRIAL_EVAL_DEPRECATION_DATE = datetime(2026, 7, 15, tzinfo=UTC)


def trial_eval_deprecation_date() -> datetime:
    override = getattr(settings, "AI_OBSERVABILITY_TRIAL_EVAL_DEPRECATION_DATE", None)
    if override:
        parsed = datetime.fromisoformat(override)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return DEFAULT_TRIAL_EVAL_DEPRECATION_DATE
