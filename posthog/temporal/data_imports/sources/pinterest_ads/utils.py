from datetime import date, datetime, timedelta
from typing import Any, Optional

import requests
import structlog
from dateutil import parser
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

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

RETRYABLE_STATUS_CODES = [429, 500, 502, 503, 504]


class PinterestAdsAPIError(Exception):
    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class PinterestAdsRetryableError(PinterestAdsAPIError):
    pass


def _is_retryable_status(status_code: int) -> bool:
    return status_code in RETRYABLE_STATUS_CODES


def _check_response(response: requests.Response) -> None:
    if response.status_code == 200:
        return

    if _is_retryable_status(response.status_code):
        raise PinterestAdsRetryableError(
            f"Pinterest Ads API error (retryable): {response.status_code} {response.text[:500]}",
            status_code=response.status_code,
        )

    raise PinterestAdsAPIError(
        f"Pinterest Ads API error: {response.status_code} {response.text[:500]}",
        status_code=response.status_code,
    )


def build_session(access_token: str) -> requests.Session:
    session = requests.Session()
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


@retry(
    retry=retry_if_exception_type(PinterestAdsRetryableError),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=2, max=60),
    reraise=True,
)
def _make_request(session: requests.Session, url: str, params: Optional[dict] = None) -> dict:
    response = session.get(url, params=params, timeout=30)
    _check_response(response)
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
            "entity_statuses": "ACTIVE,PAUSED",
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
    return [str(entity["id"]) for entity in entities if "id" in entity]


def fetch_analytics(
    session: requests.Session,
    ad_account_id: str,
    endpoint_name: str,
    entity_ids: list[str],
    start_date: str,
    end_date: str,
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
                    all_rows.append(_normalize_row(row))
            else:
                logger.error(
                    "pinterest_ads_unexpected_analytics_response",
                    endpoint=endpoint_name,
                    response_type=type(data).__name__,
                )

    return all_rows


def validate_ad_account(access_token: str, ad_account_id: str) -> tuple[bool, Optional[str]]:
    session = build_session(access_token)
    url = f"{BASE_URL}/ad_accounts/{ad_account_id}"
    try:
        response = session.get(url, timeout=10)
        if response.status_code == 200:
            return True, None
        elif response.status_code == 403:
            return False, "Access denied to this ad account. Check your permissions."
        elif response.status_code == 404:
            return False, "Ad account not found. Check your ad account ID."
        else:
            return False, f"Failed to validate ad account: {response.status_code}"
    except requests.Timeout:
        return False, "Request timed out while validating ad account"
    except Exception as e:
        return False, f"Error validating ad account: {str(e)}"
