"""The scopes a project secret API key may carry."""

from . import catalog

# llm_gateway:read is staff-only, so ProjectSecretAPIKeySerializer adds it per request.
PROJECT_SECRET_API_KEY_ALLOWED_API_SCOPE_ACTION: list[tuple[catalog.APIScopeObject, catalog.APIScopeActions]] = [
    ("endpoint", "read"),
    ("person", "write"),
    # SDK local evaluation and remote config. The Rust feature-flags service already
    # validates feature_flag:read PSAKs on the flag-definitions path; this makes them creatable.
    ("feature_flag", "read"),
    # Customer analytics external account list, a bulk export for service integrations.
    # Gated on a PSAK so the team-wide secret_api_token (readable by any project member)
    # can't be used to sidestep per-user account access controls.
    ("account", "read"),
    # Lets a service create customer analytics accounts through the external account POST.
    # Updates on that route stay team-token only.
    ("account", "write"),
    # Conversations external ticket API reads, mirroring the account scope above so
    # service integrations don't need the team-wide secret_api_token (#63111).
    ("support_ticket", "read"),
    # Endpoints are gone; kept so existing keys that hold it stay saveable.
    ("loop", "write"),
    # Read-only export of experiment definitions (list/retrieve), so services syncing
    # experiments into a warehouse don't need a credential tied to one person's account.
    ("experiment", "read"),
    ("offline_evaluation_ingestion", "write"),
    # A project's own usage and share of spend, for a service that watches one project's billing.
    # Only someone with full billing access may grant it (see the key serializer).
    ("billing", "read"),
    # Lets a service start Replay Vision scans and read their results back through `vision/requests/`.
    # Both are needed together; every other replay_scanner and session_recording route stays PSAK-denied.
    ("replay_scanner", "write"),
    ("session_recording", "read"),
    # Lets a service send transactional email (`messaging_templates/:id/send/`, `messaging/send/email/`), read a
    # send's status (`messaging/emails/:id/`) and set a recipient's topic preferences (`messaging/preferences/`).
    # Every other hog_flow route stays PSAK-denied, because no other hog_flow viewset lists PSAK actions.
    ("hog_flow", "read"),
    ("hog_flow", "write"),
    ("messaging_preference", "write"),
    ("transactional_email", "read"),
    ("transactional_email", "write"),
    # SDK prompt fetches by name and by list, so a service does not need a credential tied
    # to one person's account. Publishing, labels and archiving stay closed to these keys.
    ("llm_prompt", "read"),
    ("logs", "read"),
    # Lets a customer's own agent search and read business knowledge without a credential tied
    # to one person's account. Every write, and the sources, settings and playground routes, stay closed.
    ("business_knowledge", "read"),
]
