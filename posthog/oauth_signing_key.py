from oauth2_provider.settings import oauth2_settings

OIDC_SIGNING_KEY_MISSING_MESSAGE = (
    "OAuth is not set up on this PostHog instance. "
    "Ask the instance admin to set the OIDC_RSA_PRIVATE_KEY environment variable to an RSA private key in PEM format."
)


def oidc_signing_key_configured() -> bool:
    # Every OAuth client PostHog creates (CIMD, DCR, toolbar) uses RS256, and OAuthApplication.clean()
    # rejects RS256 without this key, so no client can be created or updated while it is unset.
    return bool(oauth2_settings.OIDC_RSA_PRIVATE_KEY)
