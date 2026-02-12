from typing import Any, Optional

import structlog

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.pinterest_ads.settings import PINTEREST_ADS_CONFIG, EndpointType
from posthog.temporal.data_imports.sources.pinterest_ads.utils import (
    build_session,
    fetch_analytics,
    fetch_entities,
    fetch_entity_ids,
    get_date_range,
)

logger = structlog.get_logger(__name__)


def pinterest_ads_source(
    ad_account_id: str,
    endpoint: str,
    access_token: str,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    if endpoint not in PINTEREST_ADS_CONFIG:
        raise ValueError(f"Unknown Pinterest Ads endpoint: {endpoint}")

    endpoint_config = PINTEREST_ADS_CONFIG[endpoint]
    session = build_session(access_token)

    if endpoint_config.endpoint_type == EndpointType.ENTITY:
        items = _fetch_entity_items(session, ad_account_id, endpoint)
    elif endpoint_config.endpoint_type == EndpointType.ANALYTICS:
        items = _fetch_analytics_items(
            session, ad_account_id, endpoint, should_use_incremental_field, db_incremental_field_last_value
        )
    else:
        raise ValueError(f"Unknown endpoint type: {endpoint_config.endpoint_type}")

    return SourceResponse(
        name=endpoint,
        items=lambda: items,
        primary_keys=endpoint_config.primary_keys,
        partition_count=1,
        partition_size=endpoint_config.partition_size,
        partition_mode=endpoint_config.partition_mode,
        partition_format=endpoint_config.partition_format,
        partition_keys=endpoint_config.partition_keys,
    )


def _fetch_entity_items(
    session: Any,
    ad_account_id: str,
    endpoint: str,
) -> list[dict[str, Any]]:
    return fetch_entities(session, ad_account_id, endpoint)


def _fetch_analytics_items(
    session: Any,
    ad_account_id: str,
    endpoint: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
) -> list[dict[str, Any]]:
    entity_ids = fetch_entity_ids(session, ad_account_id, endpoint)

    if not entity_ids:
        logger.info("pinterest_ads_no_entities_found", endpoint=endpoint, ad_account_id=ad_account_id)
        return []

    start_date, end_date = get_date_range(should_use_incremental_field, db_incremental_field_last_value)

    logger.info(
        "pinterest_ads_fetching_analytics",
        endpoint=endpoint,
        entity_count=len(entity_ids),
        start_date=start_date,
        end_date=end_date,
    )

    return fetch_analytics(session, ad_account_id, endpoint, entity_ids, start_date, end_date)
