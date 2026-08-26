class TracingAlertConfiguration:
    enabled: bool
    state: str
    consecutive_failures: int


def direct_mutations(alert: TracingAlertConfiguration) -> None:
    # ruleid: tracing-alert-state-direct-mutation
    alert.enabled = False
    # ruleid: tracing-alert-state-direct-mutation
    alert.state = "firing"
    # ruleid: tracing-alert-state-direct-mutation
    alert.consecutive_failures = 1


def queryset_mutations(queryset) -> None:
    # ruleid: tracing-alert-state-direct-mutation
    queryset.update(enabled=False)
    # ruleid: tracing-alert-state-direct-mutation
    queryset.update(state="firing")
    # ruleid: tracing-alert-state-direct-mutation
    queryset.update(consecutive_failures=1)
