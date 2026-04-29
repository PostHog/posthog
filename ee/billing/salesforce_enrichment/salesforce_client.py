from django.conf import settings

import requests
from requests.adapters import HTTPAdapter
from simple_salesforce import Salesforce
from urllib3.util.retry import Retry


def _build_retry_session() -> requests.Session:
    """Build a requests session with retry on transient errors."""
    retry = Retry(
        total=3,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
    )
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def _get_client_credentials_token(session: requests.Session | None = None) -> tuple[str, str]:
    """Exchange OAuth client credentials for an access token.

    Returns (access_token, instance_url) from the Salesforce token endpoint.
    """
    _session = session or requests.Session()
    response = _session.post(
        f"https://{settings.SALESFORCE_INTERNAL_DOMAIN}/services/oauth2/token",
        data={
            "grant_type": "client_credentials",
            "client_id": settings.SALESFORCE_INTERNAL_CONSUMER_KEY,
            "client_secret": settings.SALESFORCE_INTERNAL_CONSUMER_SECRET,
        },
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    return payload["access_token"], payload["instance_url"]


def get_salesforce_client() -> Salesforce:
    """Create and return a Salesforce client.

    Prefers OAuth Client Credentials flow when SF_INTERNAL_CONSUMER_KEY and
    SF_INTERNAL_CONSUMER_SECRET are set, falling back to legacy username/password
    auth for backward compatibility during migration.
    """
    session = _build_retry_session()

    if settings.SALESFORCE_INTERNAL_CONSUMER_KEY and settings.SALESFORCE_INTERNAL_CONSUMER_SECRET:
        access_token, instance_url = _get_client_credentials_token(session)
        return Salesforce(session_id=access_token, instance_url=instance_url, session=session)

    if settings.SALESFORCE_USERNAME and settings.SALESFORCE_PASSWORD and settings.SALESFORCE_SECURITY_TOKEN:
        return Salesforce(
            username=settings.SALESFORCE_USERNAME,
            password=settings.SALESFORCE_PASSWORD,
            security_token=settings.SALESFORCE_SECURITY_TOKEN,
            session=session,
        )

    missing = []
    if not settings.SALESFORCE_INTERNAL_CONSUMER_KEY:
        missing.append("SF_INTERNAL_CONSUMER_KEY")
    if not settings.SALESFORCE_INTERNAL_CONSUMER_SECRET:
        missing.append("SF_INTERNAL_CONSUMER_SECRET")
    if not settings.SALESFORCE_USERNAME:
        missing.append("SF_USERNAME")
    if not settings.SALESFORCE_PASSWORD:
        missing.append("SF_PASSWORD")
    if not settings.SALESFORCE_SECURITY_TOKEN:
        missing.append("SF_SECURITY_TOKEN")

    raise ValueError(f"Missing Salesforce credentials: {', '.join(missing)}")
