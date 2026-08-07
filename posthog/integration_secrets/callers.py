from enum import StrEnum


class IntegrationCaller(StrEnum):
    """The product asking for a credential.

    Passed explicitly at every call site rather than read from a setting, so the code
    says which product wanted the credential instead of the pod it happened to run in.
    One pod hosts many products, and "Django read this" is not a useful answer during an
    incident.

    This is attribution, not authorization. The service does not trust it: Django holds
    one signing key and hosts every product below, so a compromised Django pod could name
    any of them. What bounds a request is the deployment's signing key and the provider
    allowlist the service holds for it.

    Keep in step with KNOWN_PRODUCTS in
    services/integration-service/src/deployments.ts — a name the service does not
    recognise still works, it just records as "unknown".
    """

    WAREHOUSE_SOURCES = "warehouse-sources"
    CDP = "cdp"
    MESSAGING = "messaging"
    TASKS = "tasks"
    WEB_ANALYTICS = "web-analytics"
