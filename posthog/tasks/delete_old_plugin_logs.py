from django.utils import timezone

from posthog.models import PluginLogEntry

TTL_WEEKS = 1


def delete_old_plugin_logs() -> None:
    """Plugin log entries have an in-DB TTL in ClickHouse, for Postgres we need a periodic task."""
    PluginLogEntry.objects.filter(timestamp__lte=timezone.now() - timezone.timedelta(weeks=TTL_WEEKS)).delete()
