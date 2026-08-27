from typing import Any

# Kept import-free of Django and HogQL on purpose: this list is the single source of truth for two
# compilers. `ActivityLogVisibilityManager.build_exclusion_query` emits a Django Q for ORM-backed
# reads, and `activity_visibility_hogql_predicates` emits HogQL for the federated
# `system.activity_logs` read, whose module must keep the ORM off its import path.

# Activity visibility restrictions - controls which users can see certain activity logs
# Used to hide sensitive activities (e.g., impersonated logins, user account changes) from non-staff users
activity_visibility_restrictions: list[dict[str, Any]] = [
    {
        "scope": "User",
        "activities": ["logged_in", "logged_out"],
        "exclude_when": {"was_impersonated": True},
        "allow_staff": True,
    },
    {
        "scope": "User",
        "activities": ["created", "updated", "deleted"],
        "exclude_when": {},
        "allow_staff": True,
    },
    {
        "scope": "User",
        "activities": ["scim_provisioned", "scim_replaced", "scim_updated", "scim_deprovisioned"],
        "exclude_when": {},
        "allow_staff": True,
    },
    {
        # Staff-only email sending suspension flips: the acting staff user must not leak into the
        # org activity log. The customer is told via email and in-app notification instead.
        "scope": "Team",
        "activities": ["email_sending_suspended", "email_sending_unsuspended"],
        "exclude_when": {},
        "allow_staff": True,
    },
    {
        "scope": "Role",
        "activities": ["scim_provisioned", "scim_replaced", "scim_updated", "scim_deprovisioned"],
        "exclude_when": {},
        "allow_staff": True,
    },
    {
        # Instance-setting changes are staff-only operations and must not leak into the
        # org-scoped activity log endpoints, which are visible to organization admins.
        "scope": "InstanceSetting",
        "activities": ["updated"],
        "exclude_when": {},
        "allow_staff": True,
    },
    {
        # Admin AI-gateway top-ups are staff-only; keep the staff email, credit reason,
        # and wallet balance out of the org-scoped activity log endpoints.
        "scope": "AIGatewayCredit",
        "activities": ["credit_added"],
        "exclude_when": {},
        "allow_staff": True,
    },
    {
        # Support-ticket comment rows: bodies are gated on ticket access, and rows written before
        # write-time masking (see field_with_masked_contents) still hold plaintext content readable
        # with only activity_log:read. People with ticket access read the discussion on the ticket
        # itself, so nothing needs these rows in the feeds. Ticket lifecycle activities
        # (created/updated) stay visible — only comment rows are hidden.
        "scope": "Ticket",
        "activities": ["commented", "created task"],
        "exclude_when": {},
        "allow_staff": True,
    },
    {
        # As above, for customer-facing ticket messages (the literal scope the conversations
        # product writes).
        "scope": "conversations_ticket",
        "activities": ["commented", "created task"],
        "exclude_when": {},
        "allow_staff": True,
    },
]
