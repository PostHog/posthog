from django.conf import settings
from social_core.backends.open_id_connect import OpenIdConnectAuth


class OIDC(OpenIdConnectAuth):
    name = "oidc"

    def __init__(self, *args, **kwargs):
        self.OIDC_ENDPOINT = settings.OIDC_ENDPOINT
        super().__init__(*args, **kwargs)
