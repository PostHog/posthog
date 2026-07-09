import os
import sys
from datetime import datetime

import structlog

from posthog.settings.utils import assert_debug_not_in_production, get_from_env, str_to_bool

logger = structlog.get_logger(__name__)

# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
BASE_DIR: str = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

IN_UNIT_TESTING: bool = get_from_env("IN_UNIT_TESTING", False, type_cast=str_to_bool)
IN_EVAL_TESTING: bool = get_from_env("IN_EVAL_TESTING", False, type_cast=str_to_bool)  # Set in ee/hogai/eval/pytest.ini
DEBUG: bool = get_from_env("DEBUG", False, type_cast=str_to_bool)
TEST = get_from_env(
    "TEST",
    "test" in sys.argv or "reset_test_clickhouse_db" in sys.argv or sys.argv[0].endswith("pytest"),
    type_cast=str_to_bool,
)
# Interactive shells where startup noise — app-ready logs, third-party deprecation
# warnings — should stay out of the prompt. Matches Django's own subcommand
# resolution (argv[1]; global options come after the subcommand, not before).
# `shell_plus` is intentionally excluded: it has no command override to restore the
# level once the REPL opens, so forcing ERROR would silence its whole session. For
# `dbshell` there is no Python REPL (it execs the DB client), so nothing to restore.
IS_INTERACTIVE_SHELL: bool = len(sys.argv) > 1 and sys.argv[1] in ("shell", "dbshell")
COMMAND_EXEC_AUDIT_ENABLED: bool = get_from_env("COMMAND_EXEC_AUDIT_ENABLED", not TEST, type_cast=str_to_bool)
# Kill-switch for routing JSONField (jsonb) decode through orjson (see posthog/helpers/orjson_jsonfield.py).
# Process-wide once applied in ready(), so keep it disable-able via env without a code revert.
JSONFIELD_ORJSON_DECODE: bool = get_from_env("JSONFIELD_ORJSON_DECODE", True, type_cast=str_to_bool)
STATIC_COLLECTION = get_from_env("STATIC_COLLECTION", False, type_cast=str_to_bool)
DEMO: bool = get_from_env("DEMO", False, type_cast=str_to_bool)  # Whether this is a managed demo environment
CLOUD_DEPLOYMENT: str | None = get_from_env(
    "CLOUD_DEPLOYMENT",
    optional=True,
)
"""Deployment environment identifier.

Possible values:
- `US` or `EU` for PostHog **Cloud US** and PostHog **Cloud EU**.
- `DEV` for the hosted **dev/staging** environment.
- `LOCAL` or unset for the **local dev** environment.
- `E2E` for **e2e tests**.
- Unset for **self-hosted** environments.
"""
SELF_CAPTURE: bool = get_from_env("SELF_CAPTURE", DEBUG and not DEMO, type_cast=str_to_bool)
E2E_TESTING: bool = get_from_env(
    "E2E_TESTING", False, type_cast=str_to_bool
)  # whether the app is currently running for E2E tests
OPT_OUT_CAPTURE: bool = get_from_env("OPT_OUT_CAPTURE", False, type_cast=str_to_bool)
BENCHMARK: bool = get_from_env("BENCHMARK", False, type_cast=str_to_bool)
if E2E_TESTING:
    logger.warning(
        "WARNING! Environment variable E2E_TESTING is enabled. This is a security vulnerability unless you are running tests."
    )

IS_COLLECT_STATIC = len(sys.argv) > 1 and sys.argv[1] == "collectstatic"
SERVER_GATEWAY_INTERFACE = get_from_env("SERVER_GATEWAY_INTERFACE", "WSGI", type_cast=str)

# GitHub secret alert relay URL - set in US deployment to forward alerts to EU
GITHUB_SECRET_ALERT_RELAY_URL: str | None = get_from_env("GITHUB_SECRET_ALERT_RELAY_URL", optional=True)

# Internal team on PostHog Cloud US that receives `$ai_generation` /
# `$ai_embedding` events emitted by PostHog products (PostHog Code,
# background agents, etc). Used by /api/llm_analytics/personal_spend/.
# Override in tests via @override_settings to point at a per-test team.
LLM_ANALYTICS_INTERNAL_TEAM_ID: int = 2

# Shared secret for EU→US personal-spend proxy calls (products/ai_observability).
# Must hold the same value in both regions; unset disables the proxy.
PERSONAL_SPEND_CROSS_REGION_SECRET: str = get_from_env("PERSONAL_SPEND_CROSS_REGION_SECRET", "")

# Override for the AI observability trial-eval deprecation cutoff
AI_OBSERVABILITY_TRIAL_EVAL_DEPRECATION_DATE: str | None = get_from_env(
    "AI_OBSERVABILITY_TRIAL_EVAL_DEPRECATION_DATE", optional=True
)
if AI_OBSERVABILITY_TRIAL_EVAL_DEPRECATION_DATE:
    # Fail at boot on a malformed value rather than 500ing requests and temporal runs later.
    datetime.fromisoformat(AI_OBSERVABILITY_TRIAL_EVAL_DEPRECATION_DATE)

# Duckgres - URL, internal secret, and PG endpoint for the managed warehouse service
DUCKGRES_API_URL: str | None = get_from_env("DUCKGRES_API_URL", optional=True)
DUCKGRES_INTERNAL_SECRET: str | None = get_from_env("DUCKGRES_INTERNAL_SECRET", optional=True)
DUCKGRES_PG_PORT: int = get_from_env("DUCKGRES_PG_PORT", 5432, type_cast=int)

# Bulk deletion operations can be disabled during database migrations
DISABLE_BULK_DELETES: bool = get_from_env("DISABLE_BULK_DELETES", False, type_cast=str_to_bool)

if DEBUG and not TEST and not IS_INTERACTIVE_SHELL:
    logger.warning(
        [
            "Environment variable DEBUG is set - PostHog is running in DEVELOPMENT MODE!",
            "Be sure to unset DEBUG if this is supposed to be a PRODUCTION ENVIRONMENT!",
        ]
    )

# Hard stop: DEBUG must never run on a deployed cloud env (US/EU/DEV) — it relaxes auth and exposes debug surfaces.
assert_debug_not_in_production(debug=DEBUG, cloud_deployment=CLOUD_DEPLOYMENT, test=TEST)
