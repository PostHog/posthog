from django.conf import settings

from posthog.constants import RDBMS


def is_clickhouse_enabled() -> bool:
    return settings.EE_AVAILABLE and settings.PRIMARY_DB == RDBMS.CLICKHOUSE
