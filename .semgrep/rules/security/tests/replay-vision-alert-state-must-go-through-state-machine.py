class VisionAlertConfiguration:
    enabled: bool
    state: str
    consecutive_failures: int


def direct_mutations(alert: VisionAlertConfiguration) -> None:
    # ruleid: replay-vision-alert-state-direct-mutation
    alert.enabled = False
    # ruleid: replay-vision-alert-state-direct-mutation
    alert.state = "firing"
    # ruleid: replay-vision-alert-state-direct-mutation
    alert.consecutive_failures = 1


def queryset_mutations(queryset) -> None:
    # ruleid: replay-vision-alert-state-direct-mutation
    queryset.update(enabled=False)
    # ruleid: replay-vision-alert-state-direct-mutation
    queryset.update(state="firing")
    # ruleid: replay-vision-alert-state-direct-mutation
    queryset.update(consecutive_failures=1)
