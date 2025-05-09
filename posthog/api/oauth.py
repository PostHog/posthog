from datetime import timedelta
import json
import uuid
from oauth2_provider.views import TokenView, RevokeTokenView, IntrospectTokenView
from posthog.models import OAuthApplication, OAuthAccessToken
from oauth2_provider.settings import oauth2_settings
from oauth2_provider.http import OAuth2ResponseRedirect
from oauth2_provider.exceptions import OAuthToolkitError
from django.utils import timezone

from rest_framework import serializers, status
from rest_framework.views import APIView
from rest_framework.response import Response
from oauth2_provider.views.mixins import OAuthLibMixin
from oauth2_provider.views import ConnectDiscoveryInfoView, JwksInfoView, UserInfoView
from oauth2_provider.oauth2_validators import OAuth2Validator
from rest_framework.permissions import IsAuthenticated
from rest_framework.authentication import SessionAuthentication
import structlog
from django.utils.decorators import method_decorator

from posthog.models.oauth import OAuthApplicationAccessLevel, OAuthGrant, OAuthRefreshToken
from posthog.utils import render_template
from posthog.views import login_required

logger = structlog.get_logger(__name__)


class OAuthAuthorizationSerializer(serializers.Serializer):
    client_id = serializers.CharField()
    redirect_uri = serializers.CharField(required=False, allow_null=True, default=None)
    response_type = serializers.CharField(required=False)
    state = serializers.CharField(required=False, allow_null=True, default=None)
    code_challenge = serializers.CharField(required=False, allow_null=True, default=None)
    code_challenge_method = serializers.CharField(required=False, allow_null=True, default=None)
    nonce = serializers.CharField(required=False, allow_null=True, default=None)
    claims = serializers.CharField(required=False, allow_null=True, default=None)
    scope = serializers.CharField(required=False, allow_null=True, default=None)
    allow = serializers.BooleanField()
    prompt = serializers.CharField(required=False, allow_null=True, default=None)
    approval_prompt = serializers.CharField(required=False, allow_null=True, default=None)
    access_level = serializers.ChoiceField(choices=[level.value for level in OAuthApplicationAccessLevel])
    scoped_organizations = serializers.ListField(
        child=serializers.CharField(), required=False, allow_null=True, default=[]
    )
    scoped_teams = serializers.ListField(child=serializers.IntegerField(), required=False, allow_null=True, default=[])

    def validate_scoped_organizations(self, value):
        access_level = self.initial_data.get("access_level")
        if (
            (
                access_level == OAuthApplicationAccessLevel.ALL.value
                or access_level == OAuthApplicationAccessLevel.TEAM.value
            )
            and value
            and len(value) > 0
        ):
            raise serializers.ValidationError(
                f"scoped_organizations is not allowed when access_level is {access_level}"
            )

        if access_level == OAuthApplicationAccessLevel.ORGANIZATION.value and (not value or len(value) == 0):
            raise serializers.ValidationError("scoped_organizations is required when access_level is organization")
        return value

    def validate_scoped_teams(self, value):
        access_level = self.initial_data.get("access_level")
        if (
            (
                access_level == OAuthApplicationAccessLevel.ALL.value
                or access_level == OAuthApplicationAccessLevel.ORGANIZATION.value
            )
            and value
            and len(value) > 0
        ):
            raise serializers.ValidationError(f"scoped_teams is not allowed when access_level is {access_level}")

        if access_level == OAuthApplicationAccessLevel.TEAM.value and (not value or len(value) == 0):
            raise serializers.ValidationError("scoped_teams is required when access_level is team")
        return value


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
            scope=token["scope"],
            expires=expires,
            token=token["access_token"],
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
            expires = timezone.now() + timedelta(seconds=oauth2_settings.AUTHORIZATION_CODE_EXPIRE_SECONDS)
        return OAuthGrant.objects.create(
            application=request.client,
            user=request.user,
            code=code["code"],
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
                    grant = OAuthGrant.objects.get(code=code)
                    scoped_teams = grant.scoped_teams
                    scoped_organizations = grant.scoped_organizations
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
        serializer = OAuthAuthorizationSerializer(data=request.data)

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

    authentication_classes = []
    permission_classes = []
    pass


class OAuthRevokeTokenView(RevokeTokenView):
    """
    OAuth2 Revoke Token endpoint.

    This endpoint is used to revoke a token. It implements a POST request with the following parameters:
    - token: The token to revoke.
    - token_type_hint(optional): The type of token to revoke - either "access_token" or "refresh_token"
    """

    authentication_classes = []
    permission_classes = []
    pass


class OAuthIntrospectTokenView(IntrospectTokenView):
    authentication_classes = []
    permission_classes = []
    pass


class OAuthConnectDiscoveryInfoView(ConnectDiscoveryInfoView):
    authentication_classes = []
    permission_classes = []
    pass


class OAuthJwksInfoView(JwksInfoView):
    authentication_classes = []
    permission_classes = []
    pass


class OAuthUserInfoView(UserInfoView):
    authentication_classes = []
    permission_classes = []
    pass
