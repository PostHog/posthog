from urllib.parse import parse_qsl, urlparse, urlunparse

from oauth2_provider.oauth2_backends import OAuthLibCore
from oauthlib.common import urlencode

from posthog.scopes import translate_renamed_scopes


def translate_scope_param(value: str) -> str:
    """A space-separated `scope` value with renamed scopes translated, or `value` as given when none are."""
    tokens = value.split()
    translated = translate_renamed_scopes(tokens)
    return " ".join(translated) if translated != tokens else value


def _translate_scope_in_uri(uri: str) -> str:
    parsed = urlparse(uri)
    params = parse_qsl(parsed.query, keep_blank_values=True)
    translated = [(key, translate_scope_param(value) if key == "scope" else value) for key, value in params]
    if translated == params:
        return uri
    return urlunparse(parsed._replace(query=urlencode(translated)))


class CanonicalScopeOAuthLibCore(OAuthLibCore):
    """Hands oauthlib a `scope` parameter with renamed scopes translated, in the query and in the body.

    Every grant oauthlib runs (authorize, token, refresh with an explicit `scope`) parses its scopes
    from these two places, so nothing in the grant or the validator sees an old scope name.
    """

    def _get_escaped_full_path(self, request):
        return _translate_scope_in_uri(super()._get_escaped_full_path(request))

    def extract_body(self, request):
        return [
            (key, translate_scope_param(value) if key == "scope" else value)
            for key, value in super().extract_body(request)
        ]
