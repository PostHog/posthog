import dataclasses


@dataclasses.dataclass(frozen=True)
class BillingAlertInfo:
    alert_id: str
    query_key: str


@dataclasses.dataclass(frozen=True)
class BillingAlertBatchWorkflowInputs:
    alert_ids: list[str]


@dataclasses.dataclass(frozen=True)
class EvaluateBillingAlertBatchActivityInputs:
    alert_ids: list[str]
