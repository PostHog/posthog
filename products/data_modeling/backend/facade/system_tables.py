DATA_MODELING_ALLOWED_SYSTEM_TABLES: frozenset[str] = frozenset(
    {
        "_account_channel_summaries",
        "_account_custom_property_values",
        "_account_custom_property_values_history",
        "_account_email_thread_links",
        "_account_email_threads",
        "_account_meetings",
        "account_relationship_definitions",
        "account_relationships",
        "accounts",
        "custom_property_definitions",
        "feature_request_account_links",
        "feature_requests",
        "support_tickets",
    }
)
