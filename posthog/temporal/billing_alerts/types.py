import dataclasses


@dataclasses.dataclass(frozen=True)
class BillingAlertInfo:
    alert_id: str


@dataclasses.dataclass(frozen=True)
class BillingAlertBatchWorkflowInputs:
    alert_ids: list[str]


@dataclasses.dataclass(frozen=True)
class EvaluateBillingAlertBatchActivityInputs:
    alert_ids: list[str]


@dataclasses.dataclass(frozen=True)
class NotifyBillingAlertEventsActivityInputs:
    event_ids: list[str]
