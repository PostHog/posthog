from django.http.response import HttpResponse
from django.urls.base import reverse
from rest_framework.decorators import api_view
from rest_framework.exceptions import PermissionDenied
from social_core.backends.saml import SAMLAuth, SAMLIdentityProvider
from social_core.exceptions import AuthFailed, AuthMissingParameter
from social_django.utils import load_backend, load_strategy

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
    def get_idp(self, instance: "OrganizationDomain"):
        return SAMLIdentityProvider(
            "saml", entity_id=instance.saml_entity_id, url=instance.saml_acs_url, x509cert=instance.saml_x509_cert
        )

    def auth_url(self):
        """
        Overridden to use the config from the relevant OrganizationDomain
        Get the URL to which we must redirect in order to
        authenticate the user
        """
        try:
            email = self.strategy.request_data()["email"]
        except KeyError:
            raise AuthMissingParameter(self, "email")

        instance = OrganizationDomain.objects.get_verified_for_email_address(email=email)

        if not instance or not instance.has_saml:
            raise AuthFailed("saml", "SAML not configured for this user.")

        auth = self._create_saml_auth(idp=self.get_idp(instance))
        # Below, return_to sets the RelayState, which can contain
        # arbitrary data.  We use it to store the specific SAML IdP
        # name, since we multiple IdPs share the same auth_complete
        # URL.
        return auth.login(return_to=str(instance.id))

    # TODO
    def get_user_details(self, response):
        """Get user details like full name, email, etc. from the
        response - see auth_complete"""
        idp = self.get_idp(response["idp_name"])
        return idp.get_user_details(response["attributes"])

    # TODO
    def get_user_id(self, details, response):
        """
        Get the permanent ID for this user from the response.
        We prefix each ID with the name of the IdP so that we can
        connect multiple IdPs to this user.
        """
        idp = self.get_idp(response["idp_name"])
        uid = idp.get_user_permanent_id(response["attributes"])
        return "{0}:{1}".format(idp.name, uid)
