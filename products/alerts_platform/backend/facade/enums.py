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
    TRACES = "traces", "Traces"
    ERROR_TRACKING = "error_tracking", "Error tracking"


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


class PlatformAlertListState(LabeledStrEnum):
    """A state the alerts list filters on. An enabled alert is in each state one of its groups is in,
    as the API shows that group. An alert with no group is not checked yet, and a disabled alert is
    only disabled."""

    BROKEN = "broken", "Broken"
    ERRORED = "errored", "Errored"
    FIRING = "firing", "Firing"
    SNOOZED = "snoozed", "Snoozed"
    NOT_FIRING = "not_firing", "Not firing"
    DISABLED = "disabled", "Disabled"
    NOT_CHECKED = "not_checked", "Not checked yet"


class PlatformAlertMute(LabeledStrEnum):
    """Why an alert holds its messages, as the alerts list filters on it."""

    SNOOZED = "snoozed", "Snoozed"
    QUIET_HOURS = "quiet_hours", "Quiet hours"


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
