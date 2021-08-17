from typing import Any, Dict

from django.conf import settings
from jose.constants import ALGORITHMS
from social_core.backends.open_id_connect import OpenIdConnectAuth


class OIDC(OpenIdConnectAuth):
    name = "oidc"
    DEFAULT_SCOPE = ["openid", "email", "profile"]

    def __init__(self, *args, **kwargs):
        self.OIDC_ENDPOINT = settings.OIDC_ENDPOINT
        super().__init__(*args, **kwargs)

    def get_jwks_keys(self) -> Dict[str, Any]:
        keys = super().get_jwks_keys()

        for key in keys:
            if not key.get("alg"):
                # Per OpenID Connect 1.0 specs, the default should be RS256
                # https://openid.net/specs/openid-connect-core-1_0.html (3.1.3.7.7)
                key["alg"] = ALGORITHMS.RS256

        return keys
