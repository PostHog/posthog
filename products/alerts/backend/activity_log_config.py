FIELD_EXCLUSIONS = {
    "AlertConfiguration": [
        "last_checked_at",
        "next_check_at",
        "is_calculating",
        "last_notified_at",
        "last_error_at",
    ],
}


FIELD_NAME_OVERRIDES = {
    "AlertConfiguration": {
        "schedule_start_time": "schedule start time",
    },
}


SIGNAL_EXCLUSIONS = {
    "AlertConfiguration": [
        "last_checked_at",
        "next_check_at",
        "is_calculating",
        "last_notified_at",
        "last_error_at",
    ],
}
