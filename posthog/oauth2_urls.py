from django.urls import path, re_path

from posthog.api.oauth import (
    DynamicClientRegistrationView,
    OAuthAuthorizationServerMetadataView,
    OAuthAuthorizationView,
    OAuthConnectDiscoveryInfoView,
    OAuthIntrospectTokenView,
    OAuthJwksInfoView,
    OAuthRevokeTokenView,
    OAuthTokenView,
    OAuthUserInfoView,
)
from posthog.utils import opt_slash_path

app_name = "oauth2_provider"  # We need this to match the namepace of django-oauth-toolkit for reverse lookups within their views to work

urlpatterns = [
    opt_slash_path("oauth/authorize", OAuthAuthorizationView.as_view(), name="authorize"),
    opt_slash_path("oauth/token", OAuthTokenView.as_view(), name="token"),
    opt_slash_path("oauth/revoke", OAuthRevokeTokenView.as_view(), name="revoke"),
    opt_slash_path("oauth/introspect", OAuthIntrospectTokenView.as_view(), name="introspect"),
    re_path(
        r"^\.well-known/openid-configuration/?$",
        OAuthConnectDiscoveryInfoView.as_view(),
        name="oidc-connect-discovery-info",
    ),
    re_path(
        r"^\.well-known/oauth-authorization-server/?$",
        OAuthAuthorizationServerMetadataView.as_view(),
        name="oauth-authorization-server-metadata",
    ),
    path(".well-known/jwks.json", OAuthJwksInfoView.as_view(), name="jwks-info"),
    opt_slash_path("oauth/userinfo", OAuthUserInfoView.as_view(), name="user-info"),
    opt_slash_path("oauth/register", DynamicClientRegistrationView.as_view(), name="register"),
]
