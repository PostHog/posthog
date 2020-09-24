from posthog.models.utils import uuid1_macless


def generate_clickhouse_uuid() -> str:
    return str(uuid1_macless())
