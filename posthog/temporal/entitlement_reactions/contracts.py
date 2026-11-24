from posthog.dataclasses import frozen


@frozen
class EntitlementReactionsInputs:
    organization_id: str


@frozen
class ExecuteEntitlementReactorInputs:
    organization_id: str
    reactor_key: str


@frozen
class EntitlementReactionsResult:
    failed_reactor_keys: list[str]
