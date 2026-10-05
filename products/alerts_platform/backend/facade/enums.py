"""Choice vocabularies the models store and the API renders.

They live here rather than on the models because a product's facade must not import Django, and
both halves need the same list: the model to constrain what it stores, presentation to describe
what it returns. One definition means neither can drift from the other.
"""

from posthog.enums import LabeledStrEnum


class PlatformAlertConfigurationSourceKind(LabeledStrEnum):
    """The product whose data an alert evaluates."""

    LOGS = "logs", "Logs"


class PlatformAlertState(LabeledStrEnum):
    """Where one alert instance stands."""

    NOT_FIRING = "not_firing", "Not firing"
    FIRING = "firing", "Firing"
    ERRORED = "errored", "Errored"
    SNOOZED = "snoozed", "Snoozed"
    BROKEN = "broken", "Broken"


class PlatformAlertConfigurationRecurrenceUnit(LabeledStrEnum):
    """The calendar unit a configuration recurs on, when it does not recur on a minute interval."""

    DAY = "day", "Day"
    WEEK = "week", "Week"
    MONTH = "month", "Month"
