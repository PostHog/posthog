"""How a row gives out a secret from `sensitive_config` that can still be encrypted.

`DjangoBackend` removes the extra encryption layers that it can open when it loads a row (see
`peel_secret_layers`). So a value that still looks like Fernet ciphertext here is one that no
configured key can open. Every record type reads its tokens through `readable_secret`, so no
record needs the Django field to decrypt a value.
"""

from typing import Any

import structlog
from prometheus_client import Counter

logger = structlog.get_logger(__name__)


class UndecryptedIntegrationSecretError(ValueError):
    """Raised when a value read off `Integration.sensitive_config` still looks like Fernet
    ciphertext instead of the decrypted secret, and no configured key can open it.

    `sensitive_config` sets `ignore_decrypt_errors=True` so integrations written before
    encryption existed keep loading, but that same leniency means a value that fails to
    decrypt under every configured key (a lost key, a corrupted row) comes back as raw
    ciphertext rather than raising. Left unchecked, that ciphertext gets sent to the
    third-party API as if it were the real credential, which rejects it as invalid, hiding
    the actual cause behind what looks like a bad customer-supplied key.

    The message is user-facing: it lands on the failed data warehouse job as `latest_error`.
    """

    def __init__(self) -> None:
        super().__init__(
            "We couldn't read the saved credentials for this connection. Reconnect the account to start syncing again."
        )


# Reading a still-encrypted secret means the row is either recoverably over-encrypted or
# permanently unreadable. Both are invisible from the sync failure alone, so count them by kind:
# a rising `unreadable` rate means live customer credentials are being lost.
integration_secret_decrypt_counter = Counter(
    "integration_sensitive_config_decrypt_recovery",
    "Reads of an Integration secret that came back still encrypted, by recovery outcome",
    labelnames=["kind", "result"],
)


# The same value as `FERNET_TOKEN_PREFIX` in `posthog/helpers/encrypted_fields.py`. The SDK contracts
# import this module before Django loads the apps, and `posthog.helpers` imports the models.
_FERNET_TOKEN_PREFIX = "gAAAAA"


def looks_encrypted(value: object) -> bool:
    return isinstance(value, str) and value.startswith(_FERNET_TOKEN_PREFIX)


def readable_secret(*, kind: str, id: int | None, team_id: int | None, field_name: str, value: Any) -> Any:
    """`value`, or `UndecryptedIntegrationSecretError` when it is still ciphertext."""
    if not looks_encrypted(value):
        return value
    integration_secret_decrypt_counter.labels(kind=kind, result="unreadable").inc()
    logger.error(
        "integration_sensitive_config_unreadable",
        integration_id=id,
        team_id=team_id,
        kind=kind,
        field=field_name,
    )
    raise UndecryptedIntegrationSecretError()
