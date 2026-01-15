from typing import Any

from rest_framework.request import Request

from posthog.models.organization_domain import OrganizationDomain

from ee.models.scim_provisioned_user import SCIMProvisionedUser

from .auth import generate_scim_token

PII_FIELDS = {"userName", "displayName", "givenName", "familyName", "value", "display", "formatted"}


def _looks_like_email(value: str) -> bool:
    return "@" in value and "." in value.rpartition("@")[2]


def mask_string(value: str) -> str:
    """Mask a string: 1-2 chars -> *, 3+ chars -> a***b"""
    if len(value) <= 2:
        return "*" * len(value)
    return f"{value[0]}***{value[-1]}"


def mask_email(email: str) -> str:
    """Mask email local part only: a***b@example.com"""
    if "@" not in email:
        return mask_string(email)
    local, domain = email.rsplit("@", 1)
    return f"{mask_string(local)}@{domain}"


def mask_pii_value(value: Any) -> Any:
    """Mask a single PII value"""
    if not isinstance(value, str) or not value:
        return value
    if _looks_like_email(value):
        return mask_email(value)
    return mask_string(value)


def mask_scim_filter(filter_str: str) -> str:
    """Mask quoted values in SCIM filter strings, e.g. userName eq "email@example.com" """
    temp = filter_str.replace('\\"', "")
    parts = temp.split('"')
    for i in range(1, len(parts), 2):
        parts[i] = mask_pii_value(parts[i])
    return '"'.join(parts)


def mask_scim_payload(data: Any, depth: int = 0) -> Any:
    """Recursively mask PII fields in a SCIM payload."""
    if depth > 20:
        return "[DEPTH_LIMIT_EXCEEDED]"

    match data:
        case dict():
            result = {}
            for key, value in data.items():
                match value:
                    case dict():
                        result[key] = mask_scim_payload(value, depth + 1)
                    case list():
                        result[key] = [mask_scim_payload(item, depth + 1) for item in value]
                    case _:
                        result[key] = mask_pii_value(value) if key in PII_FIELDS else value
            return result
        case list():
            return [mask_scim_payload(item, depth + 1) for item in data]
        case _:
            return data


def enable_scim_for_domain(domain: OrganizationDomain) -> str:
    """
    Enable SCIM for an OrganizationDomain and generate a new bearer token.
    Returns the plain text token (only shown once).
    """
    plain_token, hashed_token = generate_scim_token()

    domain.scim_enabled = True
    domain.scim_bearer_token = hashed_token
    domain.save()

    return plain_token


def disable_scim_for_domain(domain: OrganizationDomain) -> None:
    """
    Disable SCIM for an OrganizationDomain.
    """
    domain.scim_enabled = False
    domain.scim_bearer_token = None
    domain.save()


def regenerate_scim_token(domain: OrganizationDomain) -> str:
    """
    Regenerate SCIM bearer token for a domain.
    Returns the new plain text token (only shown once).
    """
    plain_token, hashed_token = generate_scim_token()

    domain.scim_bearer_token = hashed_token
    domain.save()

    return plain_token


def get_scim_base_url(domain: OrganizationDomain, request=None) -> str:
    """
    Get the SCIM base URL for a domain.
    """
    from django.conf import settings

    base_url = settings.SITE_URL
    return f"{base_url}/scim/v2/{domain.id}"


def detect_identity_provider(request: Request) -> SCIMProvisionedUser.IdentityProvider:
    """
    Detect identity provider from request User-Agent header.
    """
    user_agent = request.META.get("HTTP_USER_AGENT", "").lower()

    if "okta" in user_agent:
        return SCIMProvisionedUser.IdentityProvider.OKTA
    elif "entra" in user_agent or "microsoft" in user_agent:
        return SCIMProvisionedUser.IdentityProvider.ENTRA_ID
    elif "google" in user_agent:
        return SCIMProvisionedUser.IdentityProvider.GOOGLE
    elif "onelogin" in user_agent:
        return SCIMProvisionedUser.IdentityProvider.ONELOGIN

    return SCIMProvisionedUser.IdentityProvider.OTHER
