"""Which of PostHog's two Cloud regions a request reached.

EU is the primary region: the callback and webhook URLs third parties hold point there, so a
request for a resource the US region owns arrives here first and has to be forwarded on.

This sits outside `posthog/ingress/` on purpose. Endpoints that are not inbound webhooks ask the
same question, and they must not take a dependency on the webhook machinery to answer it.
"""

from urllib.parse import urlparse

from django.conf import settings
from django.http import HttpRequest

PRIMARY_REGION_DOMAIN = "eu.posthog.com"
SECONDARY_REGION_DOMAIN = "us.posthog.com"

if settings.DEBUG:
    PRIMARY_REGION_DOMAIN = urlparse(settings.SITE_URL).netloc
    SECONDARY_REGION_DOMAIN = "localhost:8000"


def is_primary_region(request: HttpRequest) -> bool:
    return request.get_host() == PRIMARY_REGION_DOMAIN


def other_region_domain(domain: str) -> str:
    """The region that is not the one named.

    Most third parties hold the primary region's URL, so most forwards run to the secondary
    one. A marketplace that registered the secondary region's URL is forwarded the other way.
    """
    return SECONDARY_REGION_DOMAIN if domain == PRIMARY_REGION_DOMAIN else PRIMARY_REGION_DOMAIN
