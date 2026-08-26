"""Google Cloud service-account and Pub/Sub / Cloud Storage integrations."""

import time
from datetime import timedelta

import structlog
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import service_account
from rest_framework.exceptions import ValidationError

from posthog.models.user import User
from posthog.plugins.plugin_server_api import reload_integrations_on_workers

from . import model, refresh_tracking

logger = structlog.get_logger(__name__)


def is_unique_service_account_by_organization_id(service_account_email: str, organization_id: str) -> bool:
    """Check if the service account is only in one organization.

    This is used as a security measure to block multiple organizations from
    impersonating the same service account.

    In the future we may lift this restriction, but initially we want to make sure about
    service account ownership with this check. This complements other runtime checks in
    batch exports; see `verify_impersonated_service_account_ownership` in
    `bigquery_batch_export.py`.
    """
    same_service_account_integrations = (
        model.Integration.objects.select_related("team__organization")
        .filter(kind="google-cloud-service-account", config__service_account_email=service_account_email)
        # If private key is present, then we are not impersonating
        .exclude(sensitive_config__has_key="private_key")
    )
    for integration in same_service_account_integrations:
        if str(integration.team.organization.id) != organization_id:
            return False

    return True


class GoogleCloudServiceAccountIntegration:
    integration: model.Integration

    def __init__(self, integration: model.Integration) -> None:
        self.integration = integration

    @classmethod
    def integration_from_service_account(
        cls,
        team_id: int,
        organization_id: str,
        service_account_email: str,
        project_id: str,
        private_key: str | None = None,
        private_key_id: str | None = None,
        token_uri: str | None = None,
        created_by: User | None = None,
    ) -> model.Integration:
        if private_key is None:
            if not is_unique_service_account_by_organization_id(service_account_email, organization_id):
                raise ValidationError("Cannot create Google Cloud service account integration: Invalid service account")

        sensitive_config = {}
        is_impersonated = True
        if isinstance(private_key, str) and isinstance(private_key_id, str) and isinstance(token_uri, str):
            sensitive_config["private_key"] = private_key
            sensitive_config["private_key_id"] = private_key_id
            sensitive_config["token_uri"] = token_uri

            is_impersonated = False

        variant = "impersonated" if is_impersonated else "key-file"

        integration, _ = model.Integration.objects.update_or_create(
            team_id=team_id,
            kind=model.Integration.IntegrationKind.GOOGLE_CLOUD_SERVICE_ACCOUNT.value,
            # Including team_id to allow teams from the same organization to use the
            # same service account. Otherwise different teams would overwrite each other.
            integration_id=f"{service_account_email}-{team_id}-{variant}",
            defaults={
                "config": {
                    "project_id": project_id,
                    "service_account_email": service_account_email,
                },
                "sensitive_config": sensitive_config,
                "created_by": created_by,
            },
        )

        if integration.errors:
            integration.errors = ""
            integration.save()

        return integration

    def has_key(self) -> bool:
        """Return if this integration has a key associated with a service account.

        If not, then it is a service account we are meant to impersonate.
        """
        keys = ("private_key", "private_key_id")
        return all(key in self.integration.sensitive_config for key in keys) and all(
            self.integration.sensitive_config[key] for key in keys
        )

    @property
    def project_id(self) -> str:
        return self.integration.config["project_id"]

    @property
    def service_account_email(self) -> str:
        return self.integration.config["service_account_email"]

    @property
    def service_account_info(self) -> dict[str, str]:
        return {
            "private_key": self.integration.sensitive_config["private_key"],
            "private_key_id": self.integration.sensitive_config["private_key_id"],
            "token_uri": self.integration.sensitive_config["token_uri"],
            "client_email": self.service_account_email,
            "project_id": self.project_id,
        }


class GoogleCloudIntegration:
    supported_kinds = ["google-pubsub", "google-cloud-storage"]
    integration: model.Integration

    def __init__(self, integration: model.Integration) -> None:
        self.integration = integration

    @classmethod
    def integration_from_key(
        cls, kind: str, key_info: dict, team_id: int, created_by: User | None = None
    ) -> model.Integration:
        if kind == "google-pubsub":
            scope = "https://www.googleapis.com/auth/pubsub"
        elif kind == "google-cloud-storage":
            scope = "https://www.googleapis.com/auth/devstorage.read_write"
        else:
            raise NotImplementedError(f"Google Cloud integration kind {kind} not implemented")

        try:
            credentials = service_account.Credentials.from_service_account_info(key_info, scopes=[scope])
            credentials.refresh(GoogleRequest())
        except Exception:
            raise ValidationError(f"Failed to authenticate with provided service account key")

        integration, created = model.Integration.objects.update_or_create(
            team_id=team_id,
            kind=kind,
            integration_id=credentials.service_account_email,
            defaults={
                "config": {
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

    def access_token_expired(self, time_threshold: timedelta | None = None) -> bool:
        expires_in = self.integration.config.get("expires_in")
        refreshed_at = self.integration.config.get("refreshed_at")
        if not expires_in or not refreshed_at:
            return False

        # To be really safe we refresh if its half way through the expiry
        time_threshold = time_threshold or timedelta(seconds=expires_in / 2)

        return time.time() > refreshed_at + expires_in - time_threshold.total_seconds()

    def refresh_access_token(self):
        """
        Refresh the access token for the integration if necessary
        """
        if self.integration.kind == "google-pubsub":
            scope = "https://www.googleapis.com/auth/pubsub"
        elif self.integration.kind == "google-cloud-storage":
            scope = "https://www.googleapis.com/auth/devstorage.read_write"
        else:
            raise NotImplementedError(f"Google Cloud integration kind {self.integration.kind} not implemented")

        key_info = self.integration.sensitive_config.get("key_info", self.integration.sensitive_config)
        credentials = service_account.Credentials.from_service_account_info(key_info, scopes=[scope])

        try:
            credentials.refresh(GoogleRequest())
        except Exception:
            refresh_tracking.record_refresh_failure(self.integration)
            self.integration.save(update_fields=["config"])
            raise ValidationError(f"Failed to authenticate with provided service account key")

        # Wholesale replacement also clears any refresh backoff state
        self.integration.config = {
            "expires_in": credentials.expiry.timestamp() - int(time.time()),
            "refreshed_at": int(time.time()),
        }
        # Migrate pre-migration integrations where sensitive_config contains the
        # keyfile directly (not nested under "key_info"). Without this, setting
        # access_token pollutes the keyfile dict and breaks subsequent refreshes.
        if "key_info" not in self.integration.sensitive_config:
            self.integration.sensitive_config = {
                "key_info": self.integration.sensitive_config,
                "access_token": credentials.token,
            }
        else:
            self.integration.sensitive_config["access_token"] = credentials.token
        self.integration.save()
        reload_integrations_on_workers(self.integration.team_id, [self.integration.id])

        logger.info(f"Refreshed access token for {self}")

    def get_access_token(self) -> str:
        if self.access_token_expired():
            self.refresh_access_token()
        # Fall back to config for pre-migration integrations
        return self.integration.sensitive_config.get("access_token") or self.integration.config.get("access_token", "")
