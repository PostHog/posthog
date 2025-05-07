from oauth2_provider.views import TokenView, RevokeTokenView, IntrospectTokenView
from posthog.auth import SessionAuthentication
from posthog.models import OAuthApplication, OAuthAccessToken
from oauth2_provider.settings import oauth2_settings
from oauth2_provider.http import OAuth2ResponseRedirect
from oauth2_provider.exceptions import OAuthToolkitError
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated

from rest_framework import views, serializers, status
from rest_framework.response import Response
from oauth2_provider.views.mixins import OAuthLibMixin
from oauth2_provider.views import ConnectDiscoveryInfoView, JwksInfoView, UserInfoView
import structlog

from ..utils import render_template

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


class OAuthAuthorizationView(OAuthLibMixin, views.APIView):
    """
    Custom OAuth2 Authorization endpoint that uses DRF patterns.
    Handles both GET (authorization request) and POST (authorization response) methods.
    """

    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication]
    server_class = oauth2_settings.OAUTH2_SERVER_CLASS
    validator_class = oauth2_settings.OAUTH2_VALIDATOR_CLASS

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
                    status=error_response["error"].status_code,
                )
            return self.redirect(error_response["url"], application)

        # Return a simple JSON response with error details
        return Response(
            {
                "error": error_response["error"].error,
                "error_description": error_response["error"].description,
                "state": kwargs.get("state"),
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
    - code_verifier: The code verifier that was used to generate the code_challenge.

    To comply with RFC 6749, the data must be sent as x-www-form-urlencoded.
    """

    authentication_classes = []
    permission_classes = []
    pass


class OAuthRevokeTokenView(RevokeTokenView):
    authentication_classes = []
    permission_classes = []
    pass


class OAuthIntrospectTokenView(IntrospectTokenView):
    authentication_classes = []
    permission_classes = []
    pass


class OAuthConnectDiscoveryInfoView(ConnectDiscoveryInfoView):
    pass


class OAuthJwksInfoView(JwksInfoView):
    pass


class OAuthUserInfoView(UserInfoView):
    pass
