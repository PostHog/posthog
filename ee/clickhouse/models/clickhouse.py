from posthog.models.utils import UUIDT


def generate_clickhouse_uuid() -> str:
    return str(UUIDT())
