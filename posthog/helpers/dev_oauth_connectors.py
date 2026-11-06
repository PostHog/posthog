"""The AI connectors that send people through `/oauth/authorize`, registered on a local instance.

`generate_demo_data` registers them from their public Client ID Metadata Documents (CIMD), the
same way production registers them on their first authorization, so their name and logo match
what people see in production. The dev login tools then start a pending connection with one, so
the connector version of the login and signup screens can be tried locally.
"""

import base64
import hashlib
from urllib.parse import urlencode, urlparse

import requests
from oauth2_provider.settings import oauth2_settings

from posthog.api.oauth.cimd import CIMDFetchError, CIMDValidationError, get_or_create_cimd_application
from posthog.api.oauth.logo_uri import usable_logo_uri
from posthog.dataclasses import frozen
from posthog.models.oauth import OAuthApplication

# The documents these connectors publish (claude.com/docs/connectors/building/authentication and
# developers.openai.com/apps-sdk/build/auth). Each one is the connector's client_id.
DEV_OAUTH_CONNECTOR_CIMD_URLS: tuple[str, ...] = (
    "https://claude.ai/oauth/mcp-oauth-client-metadata",
    "https://chatgpt.com/oauth/client.json",
)

# The dev tools stop at the consent screen and never exchange the code, so one fixed verifier is enough
_DEV_CODE_VERIFIER = "posthog-local-dev-connector-code-verifier"


def _code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


@frozen
class DevOAuthConnectorSeedResult:
    created: list[str]
    failed: list[str]


def seed_dev_oauth_connectors() -> DevOAuthConnectorSeedResult:
    # OAuthApplication.clean() rejects RS256 where no OIDC RSA private key is configured
    if not oauth2_settings.OIDC_RSA_PRIVATE_KEY:
        return DevOAuthConnectorSeedResult(created=[], failed=list(DEV_OAUTH_CONNECTOR_CIMD_URLS))
    existing = set(
        OAuthApplication.objects.filter(client_id__in=DEV_OAUTH_CONNECTOR_CIMD_URLS).values_list("client_id", flat=True)
    )
    created: list[str] = []
    failed: list[str] = []
    for url in DEV_OAUTH_CONNECTOR_CIMD_URLS:
        if url in existing:
            continue
        try:
            application = get_or_create_cimd_application(url)
        # The fetcher wraps connection errors, but one raised while it streams the body comes through as is
        except (CIMDFetchError, CIMDValidationError, requests.RequestException):
            failed.append(url)
            continue
        created.append(application.name)
    return DevOAuthConnectorSeedResult(created=created, failed=failed)


@frozen
class DevOAuthConnectorLink:
    client_id: str
    client_name: str
    logo_uri: str | None
    redirect_host: str | None
    authorize_path: str


def seeded_dev_oauth_connector_links() -> list[DevOAuthConnectorLink]:
    applications = OAuthApplication.objects.filter(client_id__in=DEV_OAUTH_CONNECTOR_CIMD_URLS).order_by("name")
    links: list[DevOAuthConnectorLink] = []
    for application in applications:
        redirect_uris = application.redirect_uris.split()
        if not redirect_uris:
            continue
        query = urlencode(
            {
                "client_id": application.client_id,
                "redirect_uri": redirect_uris[0],
                "response_type": "code",
                "scope": "openid",
                "code_challenge": _code_challenge(_DEV_CODE_VERIFIER),
                "code_challenge_method": "S256",
            }
        )
        links.append(
            DevOAuthConnectorLink(
                client_id=application.client_id,
                client_name=application.name,
                logo_uri=usable_logo_uri(application.logo_uri),
                redirect_host=urlparse(redirect_uris[0]).hostname,
                authorize_path=f"/oauth/authorize/?{query}",
            )
        )
    return links
