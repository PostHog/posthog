"""Push-notification provider credentials (APNS, Firebase) and device-identity verification config."""

import time
from datetime import timedelta

from django.db import connection, transaction

import structlog
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import service_account
from rest_framework.exceptions import ValidationError

from posthog.models.user import User
from posthog.plugins.plugin_server_api import reload_integrations_on_workers

from . import model, refresh_tracking

logger = structlog.get_logger(__name__)


# `config` key holding the push device-registration identity verification policy, read by the
# push subscriptions endpoint. Owned by the customer, not by the provider credentials.
CONFIG_PUSH_IDENTITY_VERIFICATION = "push_identity_verification"

PUSH_IDENTITY_VERIFICATION_MODES = ("disabled", "optional", "required")

# `config` key holding the customer's EC (P-256) public key(s) used to verify ES256 identity tokens.
# Public halves only — the private key stays on the customer's backend. At most two, so a key can be
# rotated (register the new one, cut over, drop the old) without a gap, mirroring the secret's
# primary/backup pair.
CONFIG_PUSH_IDENTITY_PUBLIC_KEYS = "push_identity_public_keys"

MAX_PUSH_IDENTITY_PUBLIC_KEYS = 2


def _validate_push_identity_public_keys(public_keys: list[str]) -> None:
    if not isinstance(public_keys, list) or not all(isinstance(key, str) for key in public_keys):
        raise ValidationError("push_identity_public_keys must be a list of PEM-encoded public key strings")
    if len(public_keys) > MAX_PUSH_IDENTITY_PUBLIC_KEYS:
        raise ValidationError(f"push_identity_public_keys accepts at most {MAX_PUSH_IDENTITY_PUBLIC_KEYS} keys")
    for key in public_keys:
        try:
            loaded = serialization.load_pem_public_key(key.encode())
        except Exception:
            raise ValidationError("Each push_identity_public_key must be a valid PEM-encoded public key")
        # ES256 is defined over P-256 specifically. Accepting another curve (P-384/P-521) would store a
        # key the verifier can't use — jwt.decode raises InvalidKeyError against it — so reject it here.
        if not isinstance(loaded, ec.EllipticCurvePublicKey) or not isinstance(loaded.curve, ec.SECP256R1):
            raise ValidationError("push_identity_public_keys must be P-256 (secp256r1) EC public keys for ES256")


def preserved_push_config(
    team_id: int,
    kind: str,
    integration_id: str,
    push_identity_verification: str | None,
    push_identity_public_keys: list[str] | None = None,
) -> dict:
    """Config keys a push credential upsert must carry over rather than drop.

    Connecting a push integration is an upsert, and the provider helpers rebuild `config` from the
    credentials they were handed. Anything they don't know about would be lost, so rotating a Firebase
    key or APNs .p8 would silently reset an enabled identity verification policy (its mode and its
    registered public keys) back to nothing, reopening the device takeover it exists to prevent. Carry
    each existing value forward unless the caller explicitly sets a new one; pass an empty list to
    clear the public keys.
    """
    if push_identity_verification is not None and push_identity_verification not in PUSH_IDENTITY_VERIFICATION_MODES:
        raise ValidationError(
            f"push_identity_verification must be one of: {', '.join(PUSH_IDENTITY_VERIFICATION_MODES)}"
        )
    if push_identity_public_keys is not None:
        _validate_push_identity_public_keys(push_identity_public_keys)

    # Serialize concurrent setup of this one integration for the rest of the caller's transaction.
    # `select_for_update` alone only locks a row that already exists, so two first-time setups could
    # both read "no policy" and the later write would clobber a policy the earlier one had just set.
    # An advisory lock covers the not-yet-created case too, keyed on the integration's identity so it
    # only serializes writers racing for the same integration. Every writer takes it, including one
    # setting explicit values — otherwise it could slip its row in between a preserving writer's read
    # and write, and have its policy dropped.
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s, hashtext(%s))", [team_id, f"{kind}:{integration_id}"])

    existing = (
        model.Integration.objects.select_for_update()
        .filter(team_id=team_id, kind=kind, integration_id=integration_id)
        .only("config")
        .first()
    )
    existing_config = (existing.config or {}) if existing else {}
    result: dict = {}

    if push_identity_verification is not None:
        result[CONFIG_PUSH_IDENTITY_VERIFICATION] = push_identity_verification
    else:
        # Drop a stored mode we don't recognize rather than carrying it forward. The push endpoint
        # already treats an unknown mode as disabled, so preserving it would keep dead data alive, and
        # raising here would leave a corrupted integration unable to rotate its credentials.
        existing_mode = existing_config.get(CONFIG_PUSH_IDENTITY_VERIFICATION)
        if existing_mode in PUSH_IDENTITY_VERIFICATION_MODES:
            result[CONFIG_PUSH_IDENTITY_VERIFICATION] = existing_mode

    if push_identity_public_keys is not None:
        # A non-empty list sets/replaces; an empty list clears (omit the key entirely).
        if push_identity_public_keys:
            result[CONFIG_PUSH_IDENTITY_PUBLIC_KEYS] = push_identity_public_keys
    else:
        existing_keys = existing_config.get(CONFIG_PUSH_IDENTITY_PUBLIC_KEYS)
        if isinstance(existing_keys, list) and existing_keys:
            result[CONFIG_PUSH_IDENTITY_PUBLIC_KEYS] = existing_keys

    return result


class FirebaseIntegration:
    integration: model.Integration

    def __init__(self, integration: model.Integration) -> None:
        if integration.kind != "firebase":
            raise Exception("FirebaseIntegration init called with Integration with wrong 'kind'")
        self.integration = integration

    @classmethod
    def integration_from_key(
        cls,
        key_info: dict,
        team_id: int,
        created_by: User | None = None,
        push_identity_verification: str | None = None,
        push_identity_public_keys: list[str] | None = None,
    ) -> "model.Integration":
        scope = "https://www.googleapis.com/auth/firebase.messaging"

        try:
            credentials = service_account.Credentials.from_service_account_info(key_info, scopes=[scope])
            credentials.refresh(GoogleRequest())
        except Exception:
            raise ValidationError("Failed to authenticate with provided Firebase service account key")

        project_id = key_info.get("project_id")
        if not project_id:
            raise ValidationError("Service account key must contain a project_id")

        # Atomic so `preserved_push_config`'s row lock is held through the upsert that follows it.
        with transaction.atomic():
            integration, created = model.Integration.objects.update_or_create(
                team_id=team_id,
                kind="firebase",
                integration_id=project_id,
                defaults={
                    "config": {
                        **preserved_push_config(
                            team_id, "firebase", project_id, push_identity_verification, push_identity_public_keys
                        ),
                        "project_id": project_id,
                        "expires_in": credentials.expiry.timestamp() - int(time.time()),
                        "refreshed_at": int(time.time()),
                    },
                    "sensitive_config": {
                        "key_info": key_info,
                        "access_token": credentials.token,
                    },
                    "created_by": created_by,
                },
            )

        if integration.errors:
            integration.errors = ""
            integration.save()

        return integration

    @property
    def project_id(self) -> str:
        return self.integration.config.get("project_id", "")

    def access_token_expired(self, time_threshold: timedelta | None = None) -> bool:
        expires_in = self.integration.config.get("expires_in")
        refreshed_at = self.integration.config.get("refreshed_at")
        if not expires_in or not refreshed_at:
            return False

        # To be really safe we refresh if its half way through the expiry
        time_threshold = time_threshold or timedelta(seconds=expires_in / 2)
        return time.time() > refreshed_at + expires_in - time_threshold.total_seconds()

    def refresh_access_token(self) -> None:
        scope = "https://www.googleapis.com/auth/firebase.messaging"
        key_info = self.integration.sensitive_config.get("key_info", {})

        credentials = service_account.Credentials.from_service_account_info(key_info, scopes=[scope])

        try:
            credentials.refresh(GoogleRequest())
        except Exception:
            refresh_tracking.record_refresh_failure(self.integration)
            self.integration.save(update_fields=["config"])
            raise ValidationError("Failed to authenticate with provided Firebase service account key")

        refresh_tracking.record_refresh_success(self.integration)
        self.integration.config["expires_in"] = credentials.expiry.timestamp() - int(time.time())
        self.integration.config["refreshed_at"] = int(time.time())
        self.integration.sensitive_config["access_token"] = credentials.token
        self.integration.save()
        reload_integrations_on_workers(self.integration.team_id, [self.integration.id])

        logger.info(f"Refreshed access token for FirebaseIntegration {self.integration.id}")

    def get_access_token(self) -> str:
        if self.access_token_expired():
            self.refresh_access_token()
        return self.integration.sensitive_config.get("access_token", "")


class ApplePushIntegration:
    """
    Integration for Apple Push Notification Service (APNS).

    config stores:
      - team_id: Apple Developer Team ID
      - bundle_id: App bundle identifier (e.g. com.example.app)
      - key_id: The Key ID for the .p8 signing key
      - environment: "production" or "sandbox" (defaults to "production")

    sensitive_config stores:
      - signing_key: The .p8 signing key contents
    """

    integration: model.Integration

    def __init__(self, integration: model.Integration) -> None:
        if integration.kind != "apns":
            raise Exception("ApplePushIntegration init called with Integration with wrong 'kind'")
        self.integration = integration

    @classmethod
    def integration_from_key(
        cls,
        signing_key: str,
        key_id: str,
        team_id_apple: str,
        bundle_id: str,
        team_id: int,
        created_by: User | None = None,
        environment: str = "production",
        push_identity_verification: str | None = None,
        push_identity_public_keys: list[str] | None = None,
    ) -> "model.Integration":
        if not all([signing_key, key_id, team_id_apple, bundle_id]):
            raise ValidationError("All APNS fields are required: signing_key, key_id, team_id_apple, bundle_id")

        if environment not in ("production", "sandbox"):
            raise ValidationError("APNS environment must be 'production' or 'sandbox'")

        integration_id = f"{team_id_apple}.{bundle_id}"
        # Atomic so `preserved_push_config`'s row lock is held through the upsert that follows it.
        with transaction.atomic():
            integration, created = model.Integration.objects.update_or_create(
                team_id=team_id,
                kind="apns",
                integration_id=integration_id,
                defaults={
                    "config": {
                        **preserved_push_config(
                            team_id, "apns", integration_id, push_identity_verification, push_identity_public_keys
                        ),
                        "team_id": team_id_apple,
                        "bundle_id": bundle_id,
                        "key_id": key_id,
                        "environment": environment,
                    },
                    "sensitive_config": {
                        "signing_key": signing_key,
                    },
                },
            )

        if created and created_by is not None:
            integration.created_by = created_by
            integration.save(update_fields=["created_by"])

        if integration.errors:
            integration.errors = ""
            integration.save(update_fields=["errors"])

        return integration

    @property
    def team_id_apple(self) -> str:
        return self.integration.config.get("team_id", "")

    @property
    def bundle_id(self) -> str:
        return self.integration.config.get("bundle_id", "")

    @property
    def key_id(self) -> str:
        return self.integration.config.get("key_id", "")

    @property
    def signing_key(self) -> str:
        return self.integration.sensitive_config.get("signing_key", "")
