from posthog.settings.base_variables import E2E_TESTING, TEST
from posthog.settings.overrides import cmd
from posthog.settings.service_requirements import SKIP_SERVICE_VERSION_REQUIREMENTS
from posthog.settings.utils import get_from_env, str_to_bool

_default_skip_async_migrations_setup = TEST or E2E_TESTING or SKIP_SERVICE_VERSION_REQUIREMENTS or cmd != "runserver"
SKIP_ASYNC_MIGRATIONS_SETUP = get_from_env(
    "SKIP_ASYNC_MIGRATIONS_SETUP", _default_skip_async_migrations_setup, type_cast=str_to_bool
)

ASYNC_MIGRATIONS_DEFAULT_TIMEOUT_SECONDS = get_from_env(
    "ASYNC_MIGRATIONS_DEFAULT_TIMEOUT_SECONDS", 2 * 60 * 60, type_cast=int
)
