from datetime import date, datetime, timedelta
from typing import Any, Optional

import requests
import structlog
from dateutil import parser

from posthog.security.outbound_proxy import external_requests_session
from posthog.temporal.data_imports.sources.pinterest_ads.settings import (
    ANALYTICS_COLUMNS,
    ANALYTICS_ENDPOINT_PATHS,
    ANALYTICS_ENTITY_SOURCES,
    ANALYTICS_ID_PARAM_NAMES,
    ANALYTICS_MAX_DATE_RANGE_DAYS,
    ANALYTICS_MAX_IDS,
    BASE_URL,
    DEFAULT_LOOKBACK_DAYS,
    ENTITY_ENDPOINT_PATHS,
    PAGE_SIZE,
)

logger = structlog.get_logger(__name__)


def build_session(access_token: str) -> requests.Session:
    session = external_requests_session()
    session.headers.update(
        {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        }
    )
    return session


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    return {k.lower(): v for k, v in row.items()}


def _chunk_list(items: list, chunk_size: int) -> list[list]:
    return [items[i : i + chunk_size] for i in range(0, len(items), chunk_size)]


def get_date_range(
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any] = None,
) -> tuple[str, str]:
    end_date = datetime.now().strftime("%Y-%m-%d")

    if should_use_incremental_field and db_incremental_field_last_value:
        try:
            if isinstance(db_incremental_field_last_value, datetime):
                last_dt = db_incremental_field_last_value
            elif isinstance(db_incremental_field_last_value, date):
                last_dt = datetime.combine(db_incremental_field_last_value, datetime.min.time())
            elif isinstance(db_incremental_field_last_value, str):
                last_dt = parser.parse(db_incremental_field_last_value)
            else:
                last_dt = datetime.fromisoformat(str(db_incremental_field_last_value))

            start_date = last_dt.strftime("%Y-%m-%d")
        except Exception:
            logger.warning(
                "pinterest_ads_invalid_incremental_value",
                value=str(db_incremental_field_last_value),
                value_type=type(db_incremental_field_last_value).__name__,
            )
            start_date = (datetime.now() - timedelta(days=DEFAULT_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    else:
        start_date = (datetime.now() - timedelta(days=DEFAULT_LOOKBACK_DAYS)).strftime("%Y-%m-%d")

    return start_date, end_date


def _chunk_date_range(start_date: str, end_date: str) -> list[tuple[str, str]]:
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")

    chunks: list[tuple[str, str]] = []
    current = start_dt

    while current <= end_dt:
        chunk_end = min(current + timedelta(days=ANALYTICS_MAX_DATE_RANGE_DAYS - 1), end_dt)
        chunks.append((current.strftime("%Y-%m-%d"), chunk_end.strftime("%Y-%m-%d")))
        current = chunk_end + timedelta(days=1)

    return chunks


def _make_request(session: requests.Session, url: str, params: Optional[dict] = None) -> Any:
    response = session.get(url, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def fetch_entities(
    session: requests.Session,
    ad_account_id: str,
    endpoint_name: str,
) -> list[dict[str, Any]]:
    path = ENTITY_ENDPOINT_PATHS[endpoint_name].format(ad_account_id=ad_account_id)
    url = f"{BASE_URL}{path}"

    all_items: list[dict[str, Any]] = []
    bookmark: Optional[str] = None

    while True:
        params: dict[str, Any] = {
            "page_size": PAGE_SIZE,
        }
        if bookmark:
            params["bookmark"] = bookmark

        data = _make_request(session, url, params)
        items = data.get("items", [])
        all_items.extend(items)

        bookmark = data.get("bookmark")
        if not bookmark:
            break

    return all_items


def fetch_entity_ids(
    session: requests.Session,
    ad_account_id: str,
    analytics_endpoint: str,
) -> list[str]:
    entity_endpoint = ANALYTICS_ENTITY_SOURCES[analytics_endpoint]
    entities = fetch_entities(session, ad_account_id, entity_endpoint)
    return [str(entity["id"]) for entity in entities]


def fetch_analytics(
    session: requests.Session,
    ad_account_id: str,
    endpoint_name: str,
    entity_ids: list[str],
    start_date: str,
    end_date: str,
    currency: str | None = None,
) -> list[dict[str, Any]]:
    path = ANALYTICS_ENDPOINT_PATHS[endpoint_name].format(ad_account_id=ad_account_id)
    url = f"{BASE_URL}{path}"
    id_param_name = ANALYTICS_ID_PARAM_NAMES[endpoint_name]

    all_rows: list[dict[str, Any]] = []
    date_chunks = _chunk_date_range(start_date, end_date)
    id_batches = _chunk_list(entity_ids, ANALYTICS_MAX_IDS)

    for batch in id_batches:
        for chunk_start, chunk_end in date_chunks:
            params: dict[str, Any] = {
                id_param_name: ",".join(batch),
                "start_date": chunk_start,
                "end_date": chunk_end,
                "columns": ",".join(ANALYTICS_COLUMNS),
                "granularity": "DAY",
            }

            data = _make_request(session, url, params)

            if isinstance(data, list):
                for row in data:
                    normalized = _normalize_row(row)
                    if currency:
                        normalized["currency"] = currency
                    all_rows.append(normalized)
            else:
                logger.error(
                    "pinterest_ads_unexpected_analytics_response",
                    endpoint=endpoint_name,
                    response_type=type(data).__name__,
                )

    return all_rows


def fetch_account_currency(session: requests.Session, ad_account_id: str) -> str | None:
    """Fetch the currency configured on the Pinterest ad account.

    Pinterest analytics don't include currency per row,
    so we fetch it from the ad account endpoint once per sync.
    """
    url = f"{BASE_URL}/ad_accounts/{ad_account_id}"
    try:
        response = session.get(url, timeout=10)
        if response.status_code == 200:
            currency = response.json().get("currency")
            if currency:
                logger.info("pinterest_ads_account_currency", ad_account_id=ad_account_id, currency=currency)
                return str(currency)
        else:
            logger.warning(
                "pinterest_ads_currency_fetch_http_error",
                ad_account_id=ad_account_id,
                status_code=response.status_code,
            )
    except Exception as e:
        logger.warning("pinterest_ads_currency_fetch_failed", ad_account_id=ad_account_id, error=str(e))
    return None
