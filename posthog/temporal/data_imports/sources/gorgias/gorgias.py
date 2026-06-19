import re
import base64
import dataclasses
from collections.abc import Iterator
from typing import Any

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.common.http import make_tracked_session
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.gorgias.settings import GORGIAS_ENDPOINTS

# Gorgias caps `limit` at 100 on every list endpoint.
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5

# A Gorgias subdomain is a single DNS label (1-63 chars, no leading/trailing hyphen).
# Validating against this before building the URL prevents a crafted domain (e.g. one
# containing `#`, `?`, `@`, or `.`) from breaking out of the `.gorgias.com` host and
# redirecting the request — and the Basic-auth header — to an attacker-controlled host.
_VALID_SUBDOMAIN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


class GorgiasRetryableError(Exception):
    pass


@dataclasses.dataclass
class GorgiasResumeConfig:
    # Opaque, short-lived cursor token returned in `meta.next_cursor`. We only persist
    # it for the duration of a single sync (Redis TTL is 24h) — never longer-term.
    cursor: str


def normalize_domain(domain: str) -> str:
    """Reduce whatever the user pasted to the bare Gorgias subdomain.

    Accepts `acme`, `acme.gorgias.com`, or `https://acme.gorgias.com/api/` and
    returns `acme`. The result is not yet validated — `get_base_url` enforces that
    it is a single safe DNS label before it is used to build a request URL.
    """
    value = domain.strip().lower()
    value = value.removeprefix("https://").removeprefix("http://")
    value = value.split("/", 1)[0]
    value = value.removesuffix(".gorgias.com")
    return value.strip("/")


def get_base_url(domain: str) -> str:
    subdomain = normalize_domain(domain)
    if not _VALID_SUBDOMAIN.match(subdomain):
        raise ValueError(
            "Invalid Gorgias domain. Use your account subdomain (letters, digits, and hyphens only), e.g. your-company."
        )
    return f"https://{subdomain}.gorgias.com/api"


def _get_auth_header(email: str, api_key: str) -> str:
    token = base64.b64encode(f"{email}:{api_key}".encode()).decode()
    return f"Basic {token}"


def get_headers(email: str, api_key: str) -> dict[str, str]:
    return {
        "Authorization": _get_auth_header(email, api_key),
        "Accept": "application/json",
    }


def validate_credentials(domain: str, email: str, api_key: str) -> tuple[bool, str | None]:
    """Cheap probe to confirm the credentials are genuine.

    `/account` is the canonical "who am I" endpoint and the lightest call available.
    A 200 means the basic-auth pair is valid; 401/403 means it is not.
    """
    try:
        url = f"{get_base_url(domain)}/account"
    except ValueError as e:
        return False, str(e)

    try:
        session = make_tracked_session(headers=get_headers(email, api_key), redact_values=(api_key,))
        response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
    except Exception as e:
        return False, f"Could not connect to Gorgias: {e}"

    if response.status_code == 200:
        return True, None
    if response.status_code in (401, 403):
        return False, "Invalid Gorgias credentials. Check your domain, email, and API key."
    return False, f"Gorgias API returned an unexpected status: {response.status_code}"


def get_rows(
    domain: str,
    email: str,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[GorgiasResumeConfig],
) -> Iterator[Any]:
    config = GORGIAS_ENDPOINTS[endpoint]
    url = f"{get_base_url(domain)}{config.path}"
    session = make_tracked_session(headers=get_headers(email, api_key), redact_values=(api_key,))

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    cursor = resume_config.cursor if resume_config else None
    if cursor:
        logger.debug(f"Gorgias: resuming {endpoint} from saved cursor")

    @retry(
        retry=retry_if_exception_type(
            (GorgiasRetryableError, requests.ReadTimeout, requests.ConnectionError),
        ),
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def fetch_page(request_cursor: str | None) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": PAGE_SIZE, "order_by": config.order_by}
        if request_cursor:
            params["cursor"] = request_cursor

        # The tracked adapter already retries 429/5xx while honoring the Retry-After
        # header; this guard re-raises anything that slips through so tenacity can back off.
        response = session.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
        if response.status_code == 429 or response.status_code >= 500:
            raise GorgiasRetryableError(
                f"Gorgias API error (retryable): status={response.status_code}, endpoint={endpoint}"
            )
        if not response.ok:
            logger.error(f"Gorgias API error: status={response.status_code}, body={response.text}, endpoint={endpoint}")
            response.raise_for_status()
        return response.json()

    while True:
        data = fetch_page(cursor)

        items = data.get("data", [])
        if items:
            yield items

        next_cursor = (data.get("meta") or {}).get("next_cursor")
        if not next_cursor:
            break

        cursor = next_cursor
        # Save AFTER yielding so a crash re-yields the last batch (merge dedupes on the
        # primary key) instead of skipping it.
        resumable_source_manager.save_state(GorgiasResumeConfig(cursor=cursor))


def gorgias_source(
    domain: str,
    email: str,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[GorgiasResumeConfig],
) -> SourceResponse:
    config = GORGIAS_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            domain=domain,
            email=email,
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=["id"],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[config.partition_key],
        sort_mode="asc",
    )
