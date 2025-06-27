from django.urls import path, re_path
from posthog.api import oauth
from posthog.utils import opt_slash_path

app_name = "oauth2_provider"  # We need this to match the namepace of django-oauth-toolkit for reverse lookups within their views to work

urlpatterns = [
    opt_slash_path("oauth/authorize", oauth.OAuthAuthorizationView.as_view(), name="authorize"),
    opt_slash_path("oauth/token", oauth.OAuthTokenView.as_view(), name="token"),
    opt_slash_path("oauth/revoke", oauth.OAuthRevokeTokenView.as_view(), name="revoke"),
    opt_slash_path("oauth/introspect", oauth.OAuthIntrospectTokenView.as_view(), name="introspect"),
    re_path(
        r"^\.well-known/openid-configuration/?$",
        oauth.OAuthConnectDiscoveryInfoView.as_view(),
        name="oidc-connect-discovery-info",
    ),
    path(".well-known/jwks.json", oauth.OAuthJwksInfoView.as_view(), name="jwks-info"),
    opt_slash_path("oauth/userinfo", oauth.OAuthUserInfoView.as_view(), name="user-info"),
]
