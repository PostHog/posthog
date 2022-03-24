from typing import Any, Dict, List, Union

from django.core.exceptions import ValidationError as DjangoValidationError
from django.http.response import HttpResponse
from django.urls.base import reverse
from rest_framework.decorators import api_view
from rest_framework.exceptions import PermissionDenied
from social_core.backends.saml import (
    OID_COMMON_NAME,
    OID_GIVEN_NAME,
    OID_MAIL,
    OID_SURNAME,
    OID_USERID,
    SAMLAuth,
    SAMLIdentityProvider,
)
from social_core.exceptions import AuthFailed, AuthMissingParameter
from social_django.utils import load_backend, load_strategy

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.models.organization_domain import OrganizationDomain


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


class MultitenantSAMLAuth(SAMLAuth):
    """
    Implements our own version of SAML auth that supports multitenancy. Instead of relying on instance-based config via env vars,
    each organization can have multiple verified domains each with its own SAML configuration.
    """

    def get_idp(self, organization_domain_or_id: Union["OrganizationDomain", str]):

        try:
            organization_domain = (
                organization_domain_or_id
                if isinstance(organization_domain_or_id, OrganizationDomain)
                else OrganizationDomain.objects.verified_domains().get(id=organization_domain_or_id)
            )
        except (OrganizationDomain.DoesNotExist, DjangoValidationError):
            raise AuthFailed("saml", "Authentication request is invalid. Invalid RelayState.")

        if not organization_domain.organization.is_feature_available(AvailableFeature.SAML):
            raise AuthFailed("saml", "Your organization does not have the required license to use SAML.")

        return SAMLIdentityProvider(
            str(organization_domain.id),
            entity_id=organization_domain.saml_entity_id,
            url=organization_domain.saml_acs_url,
            x509cert=organization_domain.saml_x509_cert,
        )

    def auth_url(self):
        """
        Overridden to use the config from the relevant OrganizationDomain
        Get the URL to which we must redirect in order to
        authenticate the user
        """
        email = self.strategy.request_data().get("email")

        if not email:
            raise AuthMissingParameter("saml", "email")

        instance = OrganizationDomain.objects.get_verified_for_email_address(email=email)

        if not instance or not instance.has_saml:
            raise AuthFailed("saml", "SAML not configured for this user.")

        auth = self._create_saml_auth(idp=self.get_idp(instance))
        # Below, return_to sets the RelayState, which contains the ID of
        # the `OrganizationDomain`.  We use it to store the specific SAML IdP
        # name, since we multiple IdPs share the same auth_complete URL.
        return auth.login(return_to=str(instance.id))

    def _get_attr(self, response_attributes: Dict[str, Any], attribute_names: List[str], optional: bool = False) -> str:
        """
        Fetches a specific attribute from the SAML response, attempting with multiple different attribute names.
        We attempt multiple attribute names to make it easier for admins to configure SAML (less configuration to set).
        """
        output = None
        for _attr in attribute_names:
            if _attr in response_attributes:
                output = response_attributes[_attr]
                break

        if not output and not optional:
            raise AuthMissingParameter("saml", attribute_names[0])

        if isinstance(output, list):
            output = output[0]

        return output

    def get_user_details(self, response):
        """
        Overridden to find attributes across multiple possible names.
        """
        attributes = response["attributes"]
        return {
            "fullname": self._get_attr(
                attributes, ["full_name", "FULL_NAME", "fullName", OID_COMMON_NAME], optional=True
            ),
            "first_name": self._get_attr(
                attributes, ["first_name", "FIRST_NAME", "firstName", OID_GIVEN_NAME], optional=True
            ),
            "last_name": self._get_attr(attributes, ["last_name", "LAST_NAME", "lastName", OID_SURNAME], optional=True),
            "email": self._get_attr(attributes, ["email", "EMAIL", OID_MAIL]),
        }

    def get_user_id(self, details, response):
        """
        Overridden to find user ID across multiple attribute names.
        Get the permanent ID for this user from the response.
        """
        USER_ID_ATTRIBUTES = ["name_id", "NAME_ID", "nameId", OID_USERID]
        uid = self._get_attr(response["attributes"], USER_ID_ATTRIBUTES)
        return f"{response['idp_name']}:{uid}"
