class AlertConfiguration:
    enabled: bool
    state: str


def direct_mutations(alert: AlertConfiguration) -> None:
    # ruleid: insight-alert-state-direct-mutation
    alert.enabled = False
    # ruleid: insight-alert-state-direct-mutation
    alert.state = "firing"


def queryset_mutations(queryset) -> None:
    # ruleid: insight-alert-state-direct-mutation
    queryset.update(enabled=False)
    # ruleid: insight-alert-state-direct-mutation
    queryset.update(state="firing")
