import json
import uuid
from datetime import timedelta
from typing import TypedDict, cast

from django.utils import timezone
from django.utils.decorators import method_decorator

import structlog
from oauth2_provider.exceptions import OAuthToolkitError
from oauth2_provider.http import OAuth2ResponseRedirect
from oauth2_provider.oauth2_validators import OAuth2Validator
from oauth2_provider.settings import oauth2_settings
from oauth2_provider.views import (
    ConnectDiscoveryInfoView,
    IntrospectTokenView,
    JwksInfoView,
    RevokeTokenView,
    TokenView,
    UserInfoView,
)
from oauth2_provider.views.mixins import OAuthLibMixin
from rest_framework import serializers, status
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.models import OAuthAccessToken, OAuthApplication, Team, User
from posthog.models.oauth import OAuthApplicationAccessLevel, OAuthGrant, OAuthRefreshToken
from posthog.user_permissions import UserPermissions
from posthog.utils import render_template
from posthog.views import login_required

logger = structlog.get_logger(__name__)


class OAuthAuthorizationContext(TypedDict):
    user: User


class OAuthAuthorizationSerializer(serializers.Serializer):
    client_id = serializers.CharField()
    redirect_uri = serializers.CharField(required=False, allow_null=True, default=None)
    response_type = serializers.CharField(required=False)
    state = serializers.CharField(required=False, allow_null=True, default=None)
    code_challenge = serializers.CharField(required=False, allow_null=True, default=None)
    code_challenge_method = serializers.CharField(required=False, allow_null=True, default=None)
    nonce = serializers.CharField(required=False, allow_null=True, default=None)
    claims = serializers.CharField(required=False, allow_null=True, default=None)
    scope = serializers.CharField()
    allow = serializers.BooleanField()
    prompt = serializers.CharField(required=False, allow_null=True, default=None)
    approval_prompt = serializers.CharField(required=False, allow_null=True, default=None)
    access_level = serializers.ChoiceField(choices=[level.value for level in OAuthApplicationAccessLevel])
    scoped_organizations = serializers.ListField(
        child=serializers.CharField(), required=False, allow_null=True, default=[]
    )
    scoped_teams = serializers.ListField(child=serializers.IntegerField(), required=False, allow_null=True, default=[])

    def __init__(self, *args, **kwargs):
        context = kwargs.get("context", {})
        if "user" not in context:
            raise ValueError("OAuthAuthorizationSerializer requires 'user' in context")
        super().__init__(*args, **kwargs)

    def validate_scoped_organizations(self, scoped_organization_ids: list[str]) -> list[str]:
        access_level = self.initial_data.get("access_level")
        requesting_user: User = self.context["user"]
        user_permissions = UserPermissions(requesting_user)
        org_memberships = user_permissions.organization_memberships

        if access_level == OAuthApplicationAccessLevel.ORGANIZATION.value:
            if not scoped_organization_ids or len(scoped_organization_ids) == 0:
                raise serializers.ValidationError("scoped_organizations is required when access_level is organization")
            try:
                organization_uuids = [uuid.UUID(org_id) for org_id in scoped_organization_ids]
                for org_uuid in organization_uuids:
                    if org_uuid not in org_memberships or not org_memberships[org_uuid].level:
                        raise serializers.ValidationError(
                            f"You must be a member of organization '{org_uuid}' to scope access to it."
                        )
            except ValueError:
                raise serializers.ValidationError("Invalid organization UUID provided in scoped_organizations.")
            return scoped_organization_ids
        elif scoped_organization_ids and len(scoped_organization_ids) > 0:
            raise serializers.ValidationError(
                f"scoped_organizations is not allowed when access_level is {access_level}"
            )
        return []

    def validate_scoped_teams(self, scoped_team_ids: list[int]) -> list[int]:
        access_level = self.initial_data.get("access_level")
        requesting_user: User = self.context["user"]
        user_permissions = UserPermissions(requesting_user)

        if access_level == OAuthApplicationAccessLevel.TEAM.value:
            if not scoped_team_ids or len(scoped_team_ids) == 0:
                raise serializers.ValidationError("scoped_teams is required when access_level is team")

            teams = Team.objects.filter(pk__in=scoped_team_ids)
            if len(teams) != len(scoped_team_ids):
                raise serializers.ValidationError("One or more specified teams in scoped_teams do not exist.")

            for team in teams:
                if user_permissions.team(team).effective_membership_level is None:
                    raise serializers.ValidationError(
                        f"You must be a member of team '{team.id}' ({team.name}) to scope access to it."
                    )
            return scoped_team_ids
        elif scoped_team_ids and len(scoped_team_ids) > 0:
            raise serializers.ValidationError(f"scoped_teams is not allowed when access_level is {access_level}")
        return []


class OAuthValidator(OAuth2Validator):
    def get_additional_claims(self, request):
        return {
            "given_name": request.user.first_name,
            "family_name": request.user.last_name,
            "email": request.user.email,
            "email_verified": request.user.is_email_verified or False,
            "sub": str(request.user.uuid),
        }

    def _create_access_token(self, expires, request, token, source_refresh_token=None):
        id_token = token.get("id_token", None)
        if id_token:
            id_token = self._load_id_token(id_token)

        scoped_teams, scoped_organizations = self._get_scoped_teams_and_organizations(
            request, access_token=None, grant=None, refresh_token=source_refresh_token
        )

        return OAuthAccessToken.objects.create(
            user=request.user,
            scope=token.get("scope", None),
            expires=expires,
            token=token.get("access_token", None),
            id_token=id_token,
            application=request.client,
            source_refresh_token=source_refresh_token,
            scoped_teams=scoped_teams,
            scoped_organizations=scoped_organizations,
        )

    def _create_authorization_code(self, request, code, expires=None):
        scoped_teams, scoped_organizations = self._get_scoped_teams_and_organizations(
            request, access_token=None, grant=None, refresh_token=None
        )

        if not expires:
            expires = timezone.now() + timedelta(seconds=cast(int, oauth2_settings.AUTHORIZATION_CODE_EXPIRE_SECONDS))
        return OAuthGrant.objects.create(
            application=request.client,
            user=request.user,
            code=code.get("code", None),
            expires=expires,
            redirect_uri=request.redirect_uri,
            scope=" ".join(request.scopes),
            code_challenge=request.code_challenge or "",
            code_challenge_method=request.code_challenge_method or "",
            nonce=request.nonce or "",
            claims=json.dumps(request.claims or {}),
            scoped_teams=scoped_teams,
            scoped_organizations=scoped_organizations,
        )

    def _create_refresh_token(self, request, refresh_token_code, access_token, previous_refresh_token):
        if previous_refresh_token:
            token_family = previous_refresh_token.token_family
        else:
            token_family = uuid.uuid4()

        scoped_teams, scoped_organizations = self._get_scoped_teams_and_organizations(
            request, access_token=None, grant=None, refresh_token=previous_refresh_token
        )

        return OAuthRefreshToken.objects.create(
            user=request.user,
            token=refresh_token_code,
            application=request.client,
            access_token=access_token,
            token_family=token_family,
            scoped_teams=scoped_teams,
            scoped_organizations=scoped_organizations,
        )

    def _get_scoped_teams_and_organizations(
        self,
        request,
        access_token: OAuthAccessToken | None,
        grant: OAuthGrant | None = None,
        refresh_token: OAuthRefreshToken | None = None,
    ):
        scoped_teams = None
        scoped_organizations = None

        if hasattr(request, "scoped_teams") and hasattr(request, "scoped_organizations"):
            scoped_teams = request.scoped_teams
            scoped_organizations = request.scoped_organizations
        elif access_token:
            scoped_teams = access_token.scoped_teams
            scoped_organizations = access_token.scoped_organizations
        elif refresh_token:
            scoped_teams = refresh_token.scoped_teams
            scoped_organizations = refresh_token.scoped_organizations
        elif grant:
            scoped_teams = grant.scoped_teams
            scoped_organizations = grant.scoped_organizations

        if request.decoded_body:
            try:
                code = dict(request.decoded_body).get("code", None)
                if code:
                    code_grant = OAuthGrant.objects.get(code=code)
                    scoped_teams = code_grant.scoped_teams
                    scoped_organizations = code_grant.scoped_organizations
            except OAuthGrant.DoesNotExist:
                pass

        if scoped_teams is None or scoped_organizations is None:
            raise OAuthToolkitError("Unable to find scoped_teams or scoped_organizations")

        return scoped_teams, scoped_organizations


class OAuthAuthorizationView(OAuthLibMixin, APIView):
    """
    This view handles incoming requests to /authorize.

    A GET request to /authorize validates the request and decides if it should:
        a) Redirect to the redirect_uri with error parameters
        b) Show an error state (e.g. when no redirect_uri is available)
        c) Show an authorize page

    A POST request is made to /authorize with allow=True if the user authorizes the request and allow=False otherwise.
    This returns a redirect_uri in it's response body to redirect the user to. In a successful flow, this will include a code
    parameter. In a failed flow, this will include error paramaters.
    """

    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    server_class = oauth2_settings.OAUTH2_SERVER_CLASS
    validator_class = oauth2_settings.OAUTH2_VALIDATOR_CLASS

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsAuthenticated()]
        return []

    @method_decorator(login_required)
    def get(self, request, *args, **kwargs):
        try:
            scopes, credentials = self.validate_authorization_request(request)
        except OAuthToolkitError as error:
            return self.error_response(error, application=None, state=request.query_params.get("state"))

        # Handle login prompt
        if request.query_params.get("prompt") == "login":
            return Response({"error": "login_required"}, status=status.HTTP_401_UNAUTHORIZED)

        # Get application and scope details
        try:
            application = OAuthApplication.objects.get(client_id=credentials["client_id"])
        except OAuthApplication.DoesNotExist:
            return Response({"error": "Invalid client_id"}, status=status.HTTP_400_BAD_REQUEST)

        # Check for auto-approval
        if request.query_params.get("approval_prompt", oauth2_settings.REQUEST_APPROVAL_PROMPT) == "auto":
            try:
                tokens = OAuthAccessToken.objects.filter(
                    user=request.user, application=application, expires__gt=timezone.now()
                ).all()

                for token in tokens:
                    if token.allow_scopes(scopes):
                        uri, headers, body, status_code = self.create_authorization_response(
                            request=request, scopes=" ".join(scopes), credentials=credentials, allow=True
                        )
                        return Response({"redirect_uri": uri})
            except OAuthToolkitError as error:
                return self.error_response(error, application, state=request.query_params.get("state"))

        return render_template("index.html", request)

    def post(self, request, *args, **kwargs):
        serializer = OAuthAuthorizationSerializer(data=request.data, context={"user": request.user})

        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            application = OAuthApplication.objects.get(client_id=serializer.validated_data["client_id"])
        except OAuthApplication.DoesNotExist:
            return Response({"error": "Invalid client_id"}, status=status.HTTP_400_BAD_REQUEST)

        credentials = {
            "client_id": serializer.validated_data["client_id"],
            "redirect_uri": serializer.validated_data["redirect_uri"],
            "response_type": serializer.validated_data.get("response_type"),
            "state": serializer.validated_data.get("state"),
            "scoped_organizations": serializer.validated_data.get("scoped_organizations"),
            "scoped_teams": serializer.validated_data.get("scoped_teams"),
        }

        # Add optional fields if present
        for field in ["code_challenge", "code_challenge_method", "nonce", "claims"]:
            if serializer.validated_data.get(field):
                credentials[field] = serializer.validated_data[field]

        try:
            uri, headers, body, status_code = self.create_authorization_response(
                request=request,
                scopes=serializer.validated_data.get("scope", ""),
                credentials=credentials,
                allow=serializer.validated_data["allow"],
            )

        except OAuthToolkitError as error:
            return self.error_response(
                error, application, no_redirect=True, state=serializer.validated_data.get("state")
            )

        logger.debug("Success url for the request: %s", uri)

        redirect = self.redirect(uri, application)

        return Response(
            {
                "redirect_to": redirect.url,
            },
            status=status.HTTP_200_OK,
        )

    def redirect(self, redirect_to, application: OAuthApplication | None):
        if application is None:
            # The application can be None in case of an error during app validation
            # In such cases, fall back to default ALLOWED_REDIRECT_URI_SCHEMES
            allowed_schemes = oauth2_settings.ALLOWED_REDIRECT_URI_SCHEMES
        else:
            allowed_schemes = application.get_allowed_schemes()

        return OAuth2ResponseRedirect(redirect_to, allowed_schemes)

    def error_response(self, error, application, no_redirect=False, **kwargs):
        """
        Handle errors either by redirecting to redirect_uri with a json in the body containing
        error details or providing an error response
        """
        redirect, error_response = super().error_response(error, **kwargs)

        if redirect:
            if no_redirect:
                return Response(
                    {
                        "redirect_to": error_response["url"],
                    },
                    status=status.HTTP_200_OK,
                )
            return self.redirect(error_response["url"], application)

        return Response(
            {
                "error": error_response["error"].error,
                "error_description": error_response["error"].description,
            },
            status=error_response["error"].status_code,
        )


class OAuthTokenView(TokenView):
    """
    OAuth2 Token endpoint.

    This implements a POST request with the following parameters:
    - grant_type: The type of grant to use - only "authorization_code" is supported.
    - code: The authorization code received from the /authorize request.
    - redirect_uri: The redirect URI to use - this is the same as the redirect_uri used in the authorization request.
    - code_verifier: The code verifier that was used to generate the code_challenge. The code_challenge is a sha256 hash
    of the code_verifier that was sent in the authorization request.

    To comply with RFC 6749, the data must be sent as x-www-form-urlencoded.
    """

    pass


class OAuthRevokeTokenView(RevokeTokenView):
    """
    OAuth2 Revoke Token endpoint.

    This endpoint is used to revoke a token. It implements a POST request with the following parameters:
    - token: The token to revoke.
    - token_type_hint(optional): The type of token to revoke - either "access_token" or "refresh_token"
    """

    pass


class OAuthIntrospectTokenView(IntrospectTokenView):
    pass


class OAuthConnectDiscoveryInfoView(ConnectDiscoveryInfoView):
    pass


class OAuthJwksInfoView(JwksInfoView):
    pass


class OAuthUserInfoView(UserInfoView):
    pass
