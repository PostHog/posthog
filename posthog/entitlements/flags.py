import structlog

from posthog.entitlements.registry import EntitlementReactorRegistry, get_entitlement_reactor_registry
from posthog.ph_client import feature_enabled_or_false

logger = structlog.get_logger(__name__)


def enabled_reactor_keys(
    organization_id: str, *, registry: EntitlementReactorRegistry | None = None, fail_on_error: bool = True
) -> frozenset[str]:
    registry = registry if registry is not None else get_entitlement_reactor_registry()
    try:
        return frozenset(
            reactor.key
            for reactor in registry
            if feature_enabled_or_false(
                reactor.feature_flag,
                organization_id,
                groups={"organization": organization_id},
                only_evaluate_locally=True,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        if fail_on_error:
            raise
        logger.warning("entitlement_reactions_flag_failed", organization_id=organization_id, exc_info=True)
        return frozenset()
