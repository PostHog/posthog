import json

import posthoganalytics

from posthog.exceptions_capture import capture_exception
from posthog.models import Team

from products.customer_analytics.backend.facade.temporal_contracts import DEFAULT_ACCOUNT_PROPERTY_SOURCE_CONCURRENCY

# Selects the per-source fanout workflow for new account-property segment syncs. The flag is
# created default-off, so an absent flag keeps every team on the legacy workflow.
ACCOUNT_PROPERTY_SYNC_FANOUT_FLAG = "warehouse-account-property-sync-fanout"
ACCOUNT_PROPERTY_SYNC_SOURCE_CONCURRENCY_FLAG = "warehouse-account-property-sync-source-concurrency"
ACCOUNT_PROPERTY_SYNC_SOURCE_CONCURRENCY_PAYLOAD_KEY = "source_concurrency"
MAX_ACCOUNT_PROPERTY_SOURCE_CONCURRENCY = 20


def account_property_sync_fanout_enabled(team_id: int) -> bool:
    """Whether new segment syncs for the team use the fanout workflow, targeted by the team's organization.

    Fails closed: an unknown team, a missing flag, or any lookup or flag-service error selects the legacy workflow.
    """
    try:
        organization_id = _get_organization_id(team_id)
        enabled = posthoganalytics.feature_enabled(
            ACCOUNT_PROPERTY_SYNC_FANOUT_FLAG,
            organization_id,
            groups={"organization": organization_id},
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )
    except Team.DoesNotExist:
        return False
    except Exception as error:
        capture_exception(error)
        return False
    return enabled is True


def get_account_property_sync_source_concurrency(team_id: int) -> int:
    try:
        organization_id = _get_organization_id(team_id)
        payload = posthoganalytics.get_feature_flag_payload(
            ACCOUNT_PROPERTY_SYNC_SOURCE_CONCURRENCY_FLAG,
            organization_id,
            groups={"organization": organization_id},
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )
        if isinstance(payload, str):
            payload = json.loads(payload)
    except Team.DoesNotExist:
        return DEFAULT_ACCOUNT_PROPERTY_SOURCE_CONCURRENCY
    except Exception as error:
        capture_exception(error)
        return DEFAULT_ACCOUNT_PROPERTY_SOURCE_CONCURRENCY
    concurrency = (
        payload.get(ACCOUNT_PROPERTY_SYNC_SOURCE_CONCURRENCY_PAYLOAD_KEY) if isinstance(payload, dict) else None
    )
    if isinstance(concurrency, bool) or not isinstance(concurrency, int) or concurrency < 1:
        return DEFAULT_ACCOUNT_PROPERTY_SOURCE_CONCURRENCY
    return min(concurrency, MAX_ACCOUNT_PROPERTY_SOURCE_CONCURRENCY)


def _get_organization_id(team_id: int) -> str:
    return str(Team.objects.only("organization_id").get(id=team_id).organization_id)
