from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from posthog.models.subscription import Subscription


def create_subscription(**kwargs: Any) -> Subscription:
    payload = {
        "target_type": "email",
        "target_value": "test1@posthog.com,test2@posthog.com",
        "frequency": "daily",
        "interval": 1,
        "start_date": datetime(2022, 1, 1, 9, 0).replace(tzinfo=ZoneInfo("UTC")),
    }

    payload.update(kwargs)
    return Subscription.objects.create(**payload)
