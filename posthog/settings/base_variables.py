import os
import sys

import structlog

from posthog.settings.utils import get_from_env, str_to_bool

logger = structlog.get_logger(__name__)

# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
BASE_DIR: str = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DEBUG: bool = get_from_env("DEBUG", False, type_cast=str_to_bool)
TEST = "test" in sys.argv or sys.argv[0].endswith("pytest") or get_from_env("TEST", False, type_cast=str_to_bool)  # type: bool
DEMO: bool = get_from_env("DEMO", False, type_cast=str_to_bool)  # Whether this is a managed demo environment
CLOUD_DEPLOYMENT: str | None = get_from_env(
    "CLOUD_DEPLOYMENT", optional=True
)  # "US", "EU", or "DEV" - unset on self-hosted
SELF_CAPTURE: bool = get_from_env("SELF_CAPTURE", DEBUG and not DEMO, type_cast=str_to_bool)
E2E_TESTING: bool = get_from_env(
    "E2E_TESTING", False, type_cast=str_to_bool
)  # whether the app is currently running for E2E tests
OPT_OUT_CAPTURE: bool = get_from_env("OPT_OUT_CAPTURE", False, type_cast=str_to_bool)
BENCHMARK: bool = get_from_env("BENCHMARK", False, type_cast=str_to_bool)
if E2E_TESTING:
    logger.warning(
        "️WARNING! Environment variable E2E_TESTING is enabled. This is a security vulnerability unless you are running tests."
    )

IS_COLLECT_STATIC = len(sys.argv) > 1 and sys.argv[1] == "collectstatic"


if DEBUG and not TEST:
    logger.warning(
        [
            "️Environment variable DEBUG is set - PostHog is running in DEVELOPMENT MODE!",
            "Be sure to unset DEBUG if this is supposed to be a PRODUCTION ENVIRONMENT!",
        ]
    )
