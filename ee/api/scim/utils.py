from posthog.models.organization_domain import OrganizationDomain

from .auth import generate_scim_token


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
