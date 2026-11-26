FIELD_EXCLUSIONS = {
    "TicketMacro": ["usage_count", "last_used_at"],
}


FIELD_WITH_MASKED_CONTENTS = {
    # Macro replies are support content; activity-log readers may lack ticket access.
    "TicketMacro": ["body"],
}


SIGNAL_EXCLUSIONS = {
    # Inserts bump these on every use. They are not a settings edit.
    "TicketMacro": ["usage_count", "last_used_at"],
}
