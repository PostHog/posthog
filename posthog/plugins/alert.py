import json
from uuid import uuid4

from django.conf import settings

from posthog.redis import get_client


class AlertLevel:
    P0 = 0
    P1 = 1
    P2 = 2
    P3 = 3
    P4 = 4


def send_alert_to_plugins(key="", description="", level=4):
    get_client().publish(
        settings.PLUGINS_ALERT_CHANNEL,
        json.dumps(
            {
                "id": str(uuid4()),
                "key": key,
                "description": description,
                "level": level,
                "trigger_location": "django_server",
            }
        ),
    )
