# Written by checks, ownership handovers and the logs route's snooze, never by a settings edit.
platform_alert_runtime_fields = [
    "next_check_at",
    "snooze_until",
    "consecutive_failures",
    "check_status",
    "owner",
    "owner_changed_at",
    "switched_off_at",
    "updated_at",
]


FIELD_EXCLUSIONS = {
    # The reverse relations read through team-scoped managers, which fail a save outside a request.
    "PlatformAlertConfiguration": [
        *platform_alert_runtime_fields,
        "alerts",
        "threads",
        "delivery_paths",
        "delivery_holds",
        "destinations",
    ],
}


SIGNAL_EXCLUSIONS = {
    "PlatformAlertConfiguration": platform_alert_runtime_fields,
}
