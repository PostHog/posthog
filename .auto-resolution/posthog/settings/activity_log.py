from posthog.settings.base_variables import TEST
from posthog.settings.utils import get_from_env

ACTIVITY_LOG_TRANSACTION_MANAGEMENT = get_from_env("ACTIVITY_LOG_TRANSACTION_MANAGEMENT", not TEST, type_cast=bool)
