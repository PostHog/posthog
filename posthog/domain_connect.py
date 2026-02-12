"""Domain Connect protocol support for automated DNS configuration.

Implements the synchronous Domain Connect flow (with request signing) so that
users can configure DNS records at supported providers with a single click
instead of manually copy-pasting records.

See https://www.domainconnect.org/ for the protocol specification.
"""

import base64
import logging
from urllib.parse import urlencode

from django.conf import settings
from django.core.cache import cache

import requests
import dns.resolver
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey

from posthog.schema import DomainConnectProviderName

logger = logging.getLogger(__name__)

# Maps _domainconnect TXT record values (provider endpoints) to display names.
# Display names must match DomainConnectProviderName in schema-general.ts — run
# `hogli build:schema` after adding a new provider to keep frontend types in sync.
# A provider is added here only AFTER our templates are accepted in their store.
# To add a provider: submit templates to github.com/Domain-Connect/Templates,
# contact the provider, and add their endpoint here once confirmed.
#
# TODO: This is intentionally empty for now while we haven't been accepted
# to the program for any providers.
DOMAIN_CONNECT_PROVIDERS: dict[str, DomainConnectProviderName] = {
    # "api.cloudflare.com/client/v4/dns/domainconnect": "Cloudflare",
}


def discover_domain_connect(domain: str) -> dict | None:
    """Discover whether a domain's DNS provider supports Domain Connect.

    Performs a TXT lookup for _domainconnect.{domain}, checks the result against
    our provider allowlist, then fetches provider settings to get the sync URL.

    Returns a dict with provider_name, endpoint, and url_sync_ux on success,
    or None if the domain's provider is not supported.
    Results are cached for 1 hour per domain.
    """
    cache_key = f"domain_connect:discovery:{domain}"
    cached = cache.get(cache_key)
    if cached is not None:
        # We cache both hits (dict) and misses (False) to avoid repeated lookups
        return cached if cached is not False else None

    endpoint = _lookup_domain_connect_endpoint(domain)
    if not endpoint or endpoint not in DOMAIN_CONNECT_PROVIDERS:
        cache.set(cache_key, False, 60 * 60)
        return None

    provider_name = DOMAIN_CONNECT_PROVIDERS[endpoint]

    provider_settings = _fetch_provider_settings(endpoint, domain)
    if not provider_settings:
        cache.set(cache_key, False, 60 * 60)
        return None

    result = {
        "provider_name": provider_name,
        "endpoint": endpoint,
        "url_sync_ux": provider_settings["urlSyncUX"],
    }
    cache.set(cache_key, result, 60 * 60)
    return result


def build_sync_apply_url(
    url_sync_ux: str,
    provider_id: str,
    service_id: str,
    domain: str,
    variables: dict[str, str],
    redirect_uri: str | None = None,
    private_key: RSAPrivateKey | None = None,
    key_id: str | None = None,
) -> str:
    """Build a Domain Connect synchronous apply URL.

    Constructs the URL that the user's browser is redirected to in order to
    approve DNS record changes at their provider.

    If private_key is provided, the query string is signed with RS256 and
    sig= / key= parameters are appended (required by providers like Cloudflare).
    """
    base = f"{url_sync_ux}/v2/domainTemplates/providers/{provider_id}/services/{service_id}/apply"

    params: dict[str, str] = {"domain": domain}
    params.update(variables)
    if redirect_uri:
        params["redirect_uri"] = redirect_uri

    query_string = urlencode(params)

    if private_key and key_id:
        signature = sign_query_string(query_string, private_key)
        query_string += f"&sig={signature}&key={key_id}"

    return f"{base}?{query_string}"


def build_provider_apply_url(
    provider_endpoint: str,
    provider_id: str,
    service_id: str,
    domain: str,
    variables: dict[str, str],
    redirect_uri: str | None = None,
    private_key: RSAPrivateKey | None = None,
    key_id: str | None = None,
) -> str:
    """Build a Domain Connect apply URL for a specific provider, bypassing discovery.

    Used when the user manually selects a provider (e.g. "I use Cloudflare")
    and we skip the auto-detection step.
    """
    provider_settings = _fetch_provider_settings(provider_endpoint, domain)
    if not provider_settings:
        raise ValueError(f"Could not fetch settings from provider: {provider_endpoint}")

    return build_sync_apply_url(
        url_sync_ux=provider_settings["urlSyncUX"],
        provider_id=provider_id,
        service_id=service_id,
        domain=domain,
        variables=variables,
        redirect_uri=redirect_uri,
        private_key=private_key,
        key_id=key_id,
    )


def sign_query_string(query_string: str, private_key: RSAPrivateKey) -> str:
    """RSA-SHA256 sign a query string and return the base64url-encoded signature."""
    signature_bytes = private_key.sign(
        query_string.encode("utf-8"),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    return base64.urlsafe_b64encode(signature_bytes).decode("ascii")


def get_signing_key() -> RSAPrivateKey | None:
    """Load the Domain Connect signing key from settings.

    Returns None if DOMAIN_CONNECT_PRIVATE_KEY is not configured.
    """
    pem = getattr(settings, "DOMAIN_CONNECT_PRIVATE_KEY", None)
    if not pem:
        return None
    key = serialization.load_pem_private_key(pem.encode("utf-8"), password=None)
    if not isinstance(key, RSAPrivateKey):
        raise ValueError("DOMAIN_CONNECT_PRIVATE_KEY must be an RSA private key")
    return key


def get_key_id() -> str:
    """Return the key identifier used for DNS-based public key publication."""
    return getattr(settings, "DOMAIN_CONNECT_KEY_ID", "_dck1")


def extract_root_domain_and_host(fqdn: str) -> tuple[str, str]:
    """Split an FQDN into (root_domain, host_prefix).

    Examples:
        "ph.example.com"            → ("example.com", "ph")
        "track.sub.example.co.uk"   → ("example.co.uk", "track.sub")
        "example.com"               → ("example.com", "")

    Uses a heuristic: known multi-part TLDs get special handling, otherwise
    the root domain is the last two labels.
    """
    # Remove trailing dot if present
    fqdn = fqdn.rstrip(".")
    parts = fqdn.split(".")

    if len(parts) <= 1:
        return (fqdn, "")

    # Known multi-part TLD suffixes (extend as needed)
    multi_part_tlds = {
        "co.uk",
        "org.uk",
        "me.uk",
        "net.uk",
        "ac.uk",
        "co.jp",
        "or.jp",
        "ne.jp",
        "ac.jp",
        "com.au",
        "net.au",
        "org.au",
        "co.nz",
        "net.nz",
        "org.nz",
        "com.br",
        "net.br",
        "org.br",
        "co.in",
        "net.in",
        "org.in",
        "co.za",
        "com.mx",
        "co.kr",
        "com.cn",
        "net.cn",
        "org.cn",
    }

    # Check if the last N parts form a known multi-part TLD
    for n in (3, 2):
        if len(parts) >= n + 1:
            candidate_tld = ".".join(parts[-n:])
            if candidate_tld in multi_part_tlds:
                root = ".".join(parts[-(n + 1) :])
                host = ".".join(parts[: -(n + 1)])
                return (root, host)

    # Default: last 2 parts are the root domain
    root = ".".join(parts[-2:])
    host = ".".join(parts[:-2])
    return (root, host)


def get_service_id_for_region(service_prefix: str) -> str:
    """Return the service ID suffix based on the current cloud deployment region."""
    region = getattr(settings, "CLOUD_DEPLOYMENT", None)
    if region and region.upper() == "EU":
        return f"{service_prefix}-eu"
    return f"{service_prefix}-us"


def get_available_providers() -> list[dict[str, str]]:
    """Return the list of supported Domain Connect providers for UI display.

    Used when auto-detection fails so the user can manually select their provider.
    """
    return [{"endpoint": endpoint, "name": name} for endpoint, name in DOMAIN_CONNECT_PROVIDERS.items()]


# --- Context resolvers ---
# Each resolver returns (domain, service_id, variables) for a specific use case.


def resolve_email_context(integration_id: int, team_id: int) -> tuple[str, str, dict[str, str]]:
    """Resolve Domain Connect parameters for an email integration.

    Triggers SES verification to get current tokens, then extracts the
    template variables needed for the email-verification template.
    """
    from posthog.models.integration import EmailIntegration, Integration

    instance = Integration.objects.get(id=integration_id, team_id=team_id)
    if instance.kind != "email":
        raise ValueError("Integration must be of kind 'email'")

    email_integration = EmailIntegration(instance)
    verification_result = email_integration.verify()

    dns_records = verification_result.get("dnsRecords", [])
    domain = instance.config.get("domain", "")
    mail_from_subdomain = instance.config.get("mail_from_subdomain", "feedback")

    verify_token = ""
    dkim_tokens: list[str] = []
    ses_region = getattr(settings, "SES_REGION", "us-east-1")

    for record in dns_records:
        if record.get("type") == "verification" and record.get("recordType") == "TXT":
            if record.get("recordHostname", "").startswith("_amazonses"):
                verify_token = record.get("recordValue", "")
        elif record.get("type") == "dkim":
            hostname = record.get("recordHostname", "")
            token = hostname.split("._domainkey.")[0] if "._domainkey." in hostname else ""
            if token:
                dkim_tokens.append(token)

    if not verify_token or len(dkim_tokens) < 3:
        raise ValueError("Could not extract all required SES tokens. Please retry domain verification first.")

    service_id = get_service_id_for_region("email-verification")
    variables = {
        "verifyToken": verify_token,
        "dkim1": dkim_tokens[0],
        "dkim2": dkim_tokens[1],
        "dkim3": dkim_tokens[2],
        "mailFromSub": mail_from_subdomain,
        "sesRegion": ses_region,
    }
    return (domain, service_id, variables)


def resolve_proxy_context(proxy_record_id: str, organization_id: str) -> tuple[str, str, dict[str, str]]:
    """Resolve Domain Connect parameters for a proxy record.

    Extracts the root domain and host from the proxy record's FQDN.
    """
    from posthog.models import ProxyRecord

    record = ProxyRecord.objects.get(id=proxy_record_id, organization_id=organization_id)
    root_domain, host = extract_root_domain_and_host(record.domain)

    service_id = get_service_id_for_region("reverse-proxy")
    variables = {
        "host": host,
        "target": record.target_cname,
    }
    return (root_domain, service_id, variables)


def generate_apply_url(
    domain: str,
    service_id: str,
    variables: dict[str, str],
    provider_endpoint: str | None = None,
    redirect_uri: str | None = None,
) -> str:
    """Generate a Domain Connect apply URL, either via auto-discovery or a specific provider.

    Handles signing automatically if a private key is configured.
    """
    signing_key = get_signing_key()
    key_id = get_key_id() if signing_key else None

    if provider_endpoint:
        return build_provider_apply_url(
            provider_endpoint=provider_endpoint,
            provider_id="posthog.com",
            service_id=service_id,
            domain=domain,
            variables=variables,
            redirect_uri=redirect_uri,
            private_key=signing_key,
            key_id=key_id,
        )

    discovery = discover_domain_connect(domain)
    if not discovery:
        raise ValueError("Domain Connect is not available for this domain's DNS provider")

    return build_sync_apply_url(
        url_sync_ux=discovery["url_sync_ux"],
        provider_id="posthog.com",
        service_id=service_id,
        domain=domain,
        variables=variables,
        redirect_uri=redirect_uri,
        private_key=signing_key,
        key_id=key_id,
    )


# --- Internal helpers ---


def _lookup_domain_connect_endpoint(domain: str) -> str | None:
    """DNS TXT lookup for _domainconnect.{domain}.

    Returns the first TXT record value or None if not found.
    """
    try:
        answers = dns.resolver.resolve(f"_domainconnect.{domain}", "TXT")
        for rdata in answers:
            # TXT records come as a list of strings; join them
            txt_value = "".join(s.decode("utf-8") if isinstance(s, bytes) else s for s in rdata.strings)
            if txt_value:
                return txt_value.strip()
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.resolver.NoNameservers, dns.resolver.Timeout):
        pass
    except Exception:
        logger.exception("Unexpected error during Domain Connect DNS lookup for %s", domain)
    return None


def _fetch_provider_settings(endpoint: str, domain: str) -> dict | None:
    """Fetch Domain Connect settings from a provider.

    GET https://{endpoint}/v2/{domain}/settings
    Returns the parsed JSON or None on failure.
    """
    cache_key = f"domain_connect:settings:{endpoint}:{domain}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached if cached is not False else None

    url = f"https://{endpoint}/v2/{domain}/settings"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if "urlSyncUX" not in data:
            cache.set(cache_key, False, 60 * 60)
            return None
        cache.set(cache_key, data, 60 * 60)
        return data
    except (requests.RequestException, ValueError):
        logger.warning("Failed to fetch Domain Connect settings from %s", url)
        cache.set(cache_key, False, 60 * 60)
        return None
