import os

from posthog.settings.utils import get_list

# Ed25519 private keys, PEM PKCS8, that sign the Web Bot Auth key directory at
# /.well-known/http-message-signatures-directory. US only: the route 404s wherever this is unset.
WEB_BOT_AUTH_PRIVATE_KEYS_ENV_VAR_PRESENT = "WEB_BOT_AUTH_PRIVATE_KEYS" in os.environ
WEB_BOT_AUTH_PRIVATE_KEYS = get_list(os.getenv("WEB_BOT_AUTH_PRIVATE_KEYS", ""))
