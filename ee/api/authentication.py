from typing import Any, List

from django.http.response import HttpResponse
from django.urls.base import reverse
from rest_framework.decorators import api_view
from rest_framework.exceptions import PermissionDenied
from social_django.utils import load_backend, load_strategy

from posthog.models.organization import OrganizationMembership


@api_view(["GET"])
def saml_metadata_view(request, *args, **kwargs):

    if (
        not request.user.organization_memberships.get(organization=request.user.organization).level
        >= OrganizationMembership.Level.ADMIN
    ):
        raise PermissionDenied("You need to be an administrator or owner to access this resource.")

    complete_url = reverse("social:complete", args=("saml",))
    saml_backend = load_backend(load_strategy(request), "saml", redirect_uri=complete_url,)
    metadata, errors = saml_backend.generate_metadata_xml()
    if not errors:
        return HttpResponse(content=metadata, content_type="text/xml")
