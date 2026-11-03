"""Choice vocabularies the models store and the API renders.

They live here rather than on the models because a product's facade must not import Django, and
both halves need the same list: the model to constrain what it stores, presentation to describe
what it returns. One definition means neither can drift from the other.
"""

from posthog.enums import LabeledStrEnum


class PlatformAlertConfigurationSourceKind(LabeledStrEnum):
    """The product whose data an alert evaluates."""

    LOGS = "logs", "Logs"
    INSIGHT = "insight", "Insight"
    WAREHOUSE_SOURCE = "warehouse_source", "Warehouse source"
    WAREHOUSE_DESTINATION = "warehouse_destination", "Warehouse destination"
    METRICS = "metrics", "Metrics"


class PlatformAlertOwner(LabeledStrEnum):
    """The one stack that evaluates and delivers an alert, and the only one that writes it."""

    SOURCE = "source", "Source"
    PLATFORM = "platform", "Platform"


class DeliveryPath(LabeledStrEnum):
    """How the platform sends an alert it owns.

    `HOG_FUNCTION` sends nothing natively. The source emits the internal events its own stack
    emitted, and the alert's HogFunctions send exactly what they sent before the cutover.
    """

    NATIVE = "native", "Native"
    HOG_FUNCTION = "hog_function", "HogFunction"


class PlatformAlertState(LabeledStrEnum):
    """Where one alert instance stands."""

    NOT_FIRING = "not_firing", "Not firing"
    FIRING = "firing", "Firing"
    ERRORED = "errored", "Errored"
    SNOOZED = "snoozed", "Snoozed"
    BROKEN = "broken", "Broken"


class PlatformAlertCheckStatus(LabeledStrEnum):
    """Whether a configuration's checks succeed. It holds for every instance of the configuration,
    because a failed check returns no group to attribute the failure to."""

    OK = "ok", "OK"
    ERRORED = "errored", "Errored"
    BROKEN = "broken", "Broken"


class PlatformAlertConfigurationRecurrenceUnit(LabeledStrEnum):
    """The calendar unit a configuration recurs on, when it does not recur on a minute interval."""

    DAY = "day", "Day"
    WEEK = "week", "Week"
    MONTH = "month", "Month"


class HoldRelease(LabeledStrEnum):
    """What releasing a held delivery does with it."""

    SEND = "send", "Send"
    SUPPRESS = "suppress", "Suppress"


class HoldReleasedBy(LabeledStrEnum):
    """Who released a held delivery.

    A release returns the request to a retry only from the caller that released it, so the agent
    and the safety net cannot both send one evaluation.
    """

    VERDICT = "verdict", "Verdict"
    CLAIM_REFUSED = "claim_refused", "Claim refused"
    SAFETY_NET = "safety_net", "Safety net"
