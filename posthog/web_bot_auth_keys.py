import hashlib
import threading
from dataclasses import field
from functools import lru_cache

from django.conf import settings

import structlog
import posthoganalytics
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from posthog.dataclasses import frozen

logger = structlog.get_logger(__name__)

_VALIDATION_ERROR_CAPTURE_TTL_SECONDS = 3600


class WebBotAuthPrivateKeyConfigurationError(ValueError):
    pass


@frozen
class WebBotAuthPrivateKeyConfiguration:
    private_keys: tuple[Ed25519PrivateKey, ...] = field(repr=False)
    validation_error: WebBotAuthPrivateKeyConfigurationError | None = field(default=None, repr=False)


@lru_cache(maxsize=1)
def load_web_bot_auth_private_key_configuration(
    private_key_pems: tuple[str, ...], *, require_at_least_one: bool
) -> WebBotAuthPrivateKeyConfiguration:
    if require_at_least_one and not private_key_pems:
        return WebBotAuthPrivateKeyConfiguration(
            private_keys=(),
            validation_error=WebBotAuthPrivateKeyConfigurationError(
                "WEB_BOT_AUTH_PRIVATE_KEYS is present but contains no keys"
            ),
        )

    private_keys: list[Ed25519PrivateKey] = []
    for key_index, private_key_pem in enumerate(private_key_pems, start=1):
        try:
            private_key = serialization.load_pem_private_key(
                private_key_pem.replace("\\n", "\n").encode(), password=None
            )
        except (TypeError, ValueError, UnsupportedAlgorithm) as error:
            return WebBotAuthPrivateKeyConfiguration(
                private_keys=(),
                validation_error=WebBotAuthPrivateKeyConfigurationError(
                    f"WEB_BOT_AUTH_PRIVATE_KEYS entry {key_index} could not be loaded ({type(error).__name__})"
                ),
            )
        if not isinstance(private_key, Ed25519PrivateKey):
            return WebBotAuthPrivateKeyConfiguration(
                private_keys=(),
                validation_error=WebBotAuthPrivateKeyConfigurationError(
                    f"WEB_BOT_AUTH_PRIVATE_KEYS entry {key_index} is not an Ed25519 private key"
                ),
            )
        private_keys.append(private_key)

    return WebBotAuthPrivateKeyConfiguration(private_keys=tuple(private_keys))


def _validate_and_capture_web_bot_auth_private_key_configuration(private_key_pems: tuple[str, ...]) -> None:
    try:
        configuration = load_web_bot_auth_private_key_configuration(private_key_pems, require_at_least_one=True)
        if configuration.validation_error is None:
            return
        validation_error = configuration.validation_error
    except Exception as error:
        validation_error = WebBotAuthPrivateKeyConfigurationError(
            f"WEB_BOT_AUTH_PRIVATE_KEYS could not be validated ({type(error).__name__})"
        )

    try:
        from posthog.exceptions_capture import capture_exception  # noqa: PLC0415
        from posthog.utils import safe_cache_add  # noqa: PLC0415

        validation_error_digest = hashlib.sha256(str(validation_error).encode()).hexdigest()
        if not safe_cache_add(
            f"web_bot_auth_private_key_validation_error:{validation_error_digest}",
            True,
            timeout=_VALIDATION_ERROR_CAPTURE_TTL_SECONDS,
        ):
            return

        with posthoganalytics.new_context():
            posthoganalytics.set_capture_exception_code_variables_context(False)
            capture_exception(
                validation_error,
                additional_properties={
                    "component": "web_bot_auth_key_directory",
                    "configured_key_count": len(private_key_pems),
                    "setting": "WEB_BOT_AUTH_PRIVATE_KEYS",
                },
            )
    except Exception:
        logger.exception("web_bot_auth_private_key_validation_capture_failed")


def validate_web_bot_auth_private_keys_in_background(private_key_pems: tuple[str, ...]) -> threading.Thread:
    thread = threading.Thread(
        target=_validate_and_capture_web_bot_auth_private_key_configuration,
        args=(private_key_pems,),
        name="validate-web-bot-auth-private-keys",
        daemon=True,
    )
    thread.start()
    return thread


def validate_configured_web_bot_auth_private_keys_in_background() -> threading.Thread | None:
    if not settings.WEB_BOT_AUTH_PRIVATE_KEYS_ENV_VAR_PRESENT:
        return None
    try:
        return validate_web_bot_auth_private_keys_in_background(tuple(settings.WEB_BOT_AUTH_PRIVATE_KEYS))
    except Exception:
        logger.exception("web_bot_auth_private_key_validation_scheduling_failed")
        return None
