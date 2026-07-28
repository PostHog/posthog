"""Week-start-day enum the HogQL engine can import without booting Django (no settings or app registry).

`django.db.models.IntegerChoices` is plain enum machinery — defining a subclass touches neither
settings nor the app registry, so this module imports cleanly in a bare interpreter.
posthog.models.team.team re-exports `WeekStartDay` for existing callers.
"""

from django.db import models


class WeekStartDay(models.IntegerChoices):
    SUNDAY = 0, "Sunday"
    MONDAY = 1, "Monday"

    @property
    def clickhouse_mode(self) -> str:
        return "3" if self == WeekStartDay.MONDAY else "0"
