from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from django.db import connections, transaction
from django.utils import timezone

from posthog.dataclasses import frozen
from posthog.entitlements.contracts import EntitlementChange, Entitlements
from posthog.entitlements.registry import EntitlementReactorRegistry, get_entitlement_reactor_registry
from posthog.models.organization import Organization
from posthog.models.organization_entitlement_applied_state import OrganizationEntitlementAppliedState


@frozen
class ReactorExecutionResult:
    reactor_key: str
    applied: bool


def load_entitlements(organization_id: str) -> Entitlements:
    features = (
        Organization.objects.using("default")
        .values_list("available_product_features", flat=True)
        .get(id=organization_id)
    )
    return Entitlements.from_features(features or [])


def get_behind_reactor_keys(
    organization_id: str,
    current: Entitlements,
    *,
    registry: EntitlementReactorRegistry | None = None,
) -> list[str]:
    registry = registry if registry is not None else get_entitlement_reactor_registry()
    if not current.features or not registry.reactors:
        return []
    applied = {
        state.reactor_key: Entitlements.from_features(state.snapshot)
        for state in OrganizationEntitlementAppliedState.objects.using("default").filter(
            organization_id=organization_id, reactor_key__in=[reactor.key for reactor in registry]
        )
    }
    return [
        reactor.key
        for reactor in registry
        if reactor.key in applied and applied[reactor.key] != current.restricted_to(reactor.feature_keys)
    ]


def list_behind_reactor_keys(organization_id: str) -> list[str]:
    return get_behind_reactor_keys(organization_id, load_entitlements(organization_id))


_REACTOR_LOCK_TIMEOUT_MS = 5_000


@contextmanager
def _reactor_execution(organization_id: str, reactor_key: str) -> Iterator[None]:
    with transaction.atomic(using="default", durable=True):
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT set_config('lock_timeout', %s, true)", [f"{_REACTOR_LOCK_TIMEOUT_MS}ms"])
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                [f"entitlement-reactor:{UUID(organization_id)}:{reactor_key}"],
            )
        yield


def execute_entitlement_reactor(organization_id: str, reactor_key: str) -> ReactorExecutionResult:
    """Commit a reactor's default-database writes and checkpoint together.

    Reactors must keep external effects and writes to other database aliases out of this transaction.
    They are not rolled back or serialized by this boundary.
    """
    reactor = get_entitlement_reactor_registry().selected([reactor_key])[0]
    with _reactor_execution(organization_id, reactor_key):
        current = load_entitlements(organization_id)
        if not current.features:
            return ReactorExecutionResult(reactor_key=reactor_key, applied=False)
        target = current.restricted_to(reactor.feature_keys)
        state = (
            OrganizationEntitlementAppliedState.objects.using("default")
            .filter(organization_id=organization_id, reactor_key=reactor_key)
            .first()
        )
        if state is None:
            return ReactorExecutionResult(reactor_key=reactor_key, applied=False)
        previous = Entitlements.from_features(state.snapshot)
        if previous == target:
            return ReactorExecutionResult(reactor_key=reactor_key, applied=False)
        reactor.react(EntitlementChange(organization_id=organization_id, previous=previous, current=target))
        OrganizationEntitlementAppliedState.objects.using("default").update_or_create(
            organization_id=organization_id,
            reactor_key=reactor_key,
            defaults={"snapshot": target.to_snapshot(), "applied_at": timezone.now()},
        )
        return ReactorExecutionResult(reactor_key=reactor_key, applied=True)
