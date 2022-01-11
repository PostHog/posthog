from posthog.settings.base_variables import E2E_TESTING, TEST
from posthog.settings.overrides import cmd
from posthog.settings.service_requirements import SKIP_SERVICE_VERSION_REQUIREMENTS
from posthog.settings.utils import get_from_env, str_to_bool

AUTO_START_ASYNC_MIGRATIONS = get_from_env("AUTO_START_ASYNC_MIGRATIONS", False, type_cast=str_to_bool)

_default_skip_async_migrations_setup = TEST or E2E_TESTING or SKIP_SERVICE_VERSION_REQUIREMENTS or cmd != "runserver"
SKIP_ASYNC_MIGRATIONS_SETUP = get_from_env(
    "SKIP_ASYNC_MIGRATIONS_SETUP", _default_skip_async_migrations_setup, type_cast=str_to_bool
)

ASYNC_MIGRATIONS_ROLLBACK_TIMEOUT = get_from_env("ASYNC_MIGRATION_ROLLBACK_TIMEOUT", 30, type_cast=int)
ASYNC_MIGRATIONS_DISABLE_AUTO_ROLLBACK = get_from_env(
    "ASYNC_MIGRATIONS_DISABLE_AUTO_ROLLBACK", False, type_cast=str_to_bool
)
