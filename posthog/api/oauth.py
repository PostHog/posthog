from oauth2_provider.views import AuthorizationView, TokenView, RevokeTokenView, IntrospectTokenView
from posthog.models import OAuthApplication, OAuthAccessToken
from oauth2_provider.models import get_scopes_backend
from oauth2_provider.settings import oauth2_settings
from oauth2_provider.exceptions import OAuthToolkitError
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
import json
from posthog.auth import SessionAuthentication
from posthog.utils import render_template


class OAuthAuthorizationView(AuthorizationView):
    template_name = None

    authentication_classes = [SessionAuthentication]  # We want the user to have an active session to authorize
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        try:
            scopes, credentials = self.validate_authorization_request(request)
        except OAuthToolkitError as error:
            # Application is not available at this time.
            return self.error_response(error, application=None)

        prompt = request.GET.get("prompt")
        if prompt == "login":
            return self.handle_prompt_login()

        all_scopes = get_scopes_backend().get_all_scopes()
        kwargs["scopes_descriptions"] = [all_scopes[scope] for scope in scopes]
        kwargs["scopes"] = scopes
        # at this point we know an Application instance with such client_id exists in the database

        application = OAuthApplication.objects.get(client_id=credentials["client_id"])

        kwargs["application"] = application
        kwargs["client_id"] = credentials["client_id"]
        kwargs["redirect_uri"] = credentials["redirect_uri"]
        kwargs["response_type"] = credentials["response_type"]
        kwargs["state"] = credentials["state"]
        if "code_challenge" in credentials:
            kwargs["code_challenge"] = credentials["code_challenge"]
        if "code_challenge_method" in credentials:
            kwargs["code_challenge_method"] = credentials["code_challenge_method"]
        if "nonce" in credentials:
            kwargs["nonce"] = credentials["nonce"]
        if "claims" in credentials:
            kwargs["claims"] = json.dumps(credentials["claims"])

        self.oauth2_data = kwargs
        # following two loc are here only because of https://code.djangoproject.com/ticket/17795
        form = self.get_form(self.get_form_class())
        kwargs["form"] = form

        # Check to see if the user has already granted access and return
        # a successful response depending on "approval_prompt" url parameter
        require_approval = request.GET.get("approval_prompt", oauth2_settings.REQUEST_APPROVAL_PROMPT)

        if "ui_locales" in credentials and isinstance(credentials["ui_locales"], list):
            # Make sure ui_locales a space separated string for oauthlib to handle it correctly.
            credentials["ui_locales"] = " ".join(credentials["ui_locales"])

        try:
            if require_approval == "auto":
                tokens = OAuthAccessToken.objects.filter(
                    user=request.user, application=kwargs["application"], expires__gt=timezone.now()
                ).all()

                # check past authorizations regarded the same scopes as the current one
                for token in tokens:
                    if token.allow_scopes(scopes):
                        uri, headers, body, status = self.create_authorization_response(
                            request=self.request,
                            scopes=" ".join(scopes),
                            credentials=credentials,
                            allow=True,
                        )
                        return self.redirect(uri, application)

        except OAuthToolkitError as error:
            return self.error_response(error, application)

        return render_template("index.html", request)


class OAuthTokenView(TokenView):
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
