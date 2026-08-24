"""The Integration Django model, its manager, and generic secret-decryption helpers."""

from typing import Any, Self, cast

from django.db import models
from django.db.models import Q
from django.utils.functional import Promise

import structlog
from prometheus_client import Counter

from posthog.helpers.encrypted_fields import FERNET_TOKEN_PREFIX, EncryptedJSONField
from posthog.models.user import User
from posthog.rbac.decorators import field_access_control
from posthog.sync import database_sync_to_async

from . import common

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


def _decrypted_sensitive_value(integration: "Integration", field_name: str) -> str | None:
    """Read a secret off `sensitive_config`, peeling any extra encryption layers it picked up.

    A read-then-save of a row whose secret failed to decrypt writes that ciphertext back
    encrypted again, so the stored value ends up double-encrypted. One decrypt (the field's
    own) then leaves ciphertext behind. Peel the rest here: the underlying secret is intact
    and the connection keeps working.
    """
    value = integration.sensitive_config.get(field_name)
    if not isinstance(value, str) or not value.startswith(FERNET_TOKEN_PREFIX):
        return value

    # django-stubs can't see through `field_access_control`, so it doesn't know this field name.
    field = cast(EncryptedJSONField, integration._meta.get_field("sensitive_config"))  # type: ignore[misc]
    recovered = field.decrypt_all_layers(value)

    if recovered is None:
        integration_secret_decrypt_counter.labels(kind=integration.kind, result="unreadable").inc()
        logger.error(
            "integration_sensitive_config_unreadable",
            integration_id=integration.pk,
            team_id=integration.team_id,
            kind=integration.kind,
            field=field_name,
        )
        raise UndecryptedIntegrationSecretError()

    integration_secret_decrypt_counter.labels(kind=integration.kind, result="recovered").inc()
    logger.warning(
        "integration_sensitive_config_over_encrypted",
        integration_id=integration.pk,
        team_id=integration.team_id,
        kind=integration.kind,
        field=field_name,
    )
    return recovered


class IntegrationQuerySet(models.QuerySet["Integration"]):
    def for_github_installation_id(self, installation_id: str | int) -> Self:
        return self.filter(
            Q(config__installation_id=str(installation_id)) | Q(config__installation_id=int(installation_id))
        )


class IntegrationManager(models.Manager["Integration"]):
    _queryset_class = IntegrationQuerySet

    def get_queryset(self) -> IntegrationQuerySet:
        return IntegrationQuerySet(self.model, using=self._db)

    def filter(self, *args: Any, **kwargs: Any) -> IntegrationQuerySet:
        return self.get_queryset().filter(*args, **kwargs)

    def first_github_for_team_installation(self, team_id: int, installation_id: str) -> "Integration | None":
        return (
            self.filter(team_id=team_id, kind=Integration.IntegrationKind.GITHUB)
            .for_github_installation_id(installation_id)
            .first()
        )

    def first_github_for_user_installation(self, user: User, installation_id: str) -> "Integration | None":
        user_team_ids = user.teams.values_list("id", flat=True)
        return (
            self.filter(team_id__in=user_team_ids, kind=Integration.IntegrationKind.GITHUB)
            .for_github_installation_id(installation_id)
            .first()
        )


def integration_kind_choices() -> list[tuple[str, str | Promise]]:
    # Callable so growing the enum doesn't generate a no-op migration.
    return list(Integration.IntegrationKind.choices)


class Integration(models.Model):
    class IntegrationKind(models.TextChoices):
        ANTHROPIC = "anthropic"
        APPLE_PUSH = "apns"
        AWS_REDSHIFT = "aws-redshift"
        AWS_S3 = "aws-s3"
        AZURE_BLOB = "azure-blob"
        BING_ADS = "bing-ads"
        CLICKUP = "clickup"
        CUSTOMERIO_APP = "customerio-app"
        CUSTOMERIO_TRACK = "customerio-track"
        CUSTOMERIO_WEBHOOK = "customerio-webhook"
        DATABRICKS = "databricks"
        EMAIL = "email"
        FIREBASE = "firebase"
        GITHUB = "github"
        GITLAB = "gitlab"
        GOOGLE_ADS = "google-ads"
        GOOGLE_ANALYTICS = "google-analytics"
        GOOGLE_CALENDAR = "google-calendar"
        GOOGLE_CLOUD_SERVICE_ACCOUNT = "google-cloud-service-account"
        GOOGLE_CLOUD_STORAGE = "google-cloud-storage"
        GOOGLE_PUBSUB = "google-pubsub"
        GOOGLE_SEARCH_CONSOLE = "google-search-console"
        GOOGLE_SHEETS = "google-sheets"
        HUBSPOT = "hubspot"
        INSTAGRAM = "instagram"
        INTERCOM = "intercom"
        JIRA = "jira"
        LINEAR = "linear"
        LINKEDIN_ADS = "linkedin-ads"
        META_ADS = "meta-ads"
        PARDOT = "pardot"
        PINTEREST_ADS = "pinterest-ads"
        POSTGRESQL = "postgresql"
        POSTHOG = "posthog"
        REDDIT_ADS = "reddit-ads"
        RESEND = "resend"
        S3_COMPATIBLE = "s3-compatible"
        SALESFORCE = "salesforce"
        SLACK = "slack"
        # Deprecated — kept in choices to avoid a no-op migration. The runtime no longer creates
        # or reads this kind; see `products/slack_app/backend/api.py` for the live integration.
        SLACK_POSTHOG_CODE = "slack-posthog-code"
        SNAPCHAT = "snapchat"
        SNOWFLAKE = "snowflake"
        STRIPE = "stripe"
        TIKTOK_ADS = "tiktok-ads"
        TWILIO = "twilio"
        VERCEL = "vercel"
        YOUTUBE_ANALYTICS = "youtube-analytics"

    team = models.ForeignKey("Team", on_delete=models.CASCADE)

    # The integration type identifier
    kind = field_access_control(models.CharField(max_length=32, choices=integration_kind_choices), "project", "admin")
    # The ID of the integration in the external system
    integration_id = field_access_control(models.TextField(null=True, blank=True), "project", "admin")
    # Any config that COULD be passed to the frontend
    config = field_access_control(models.JSONField(default=dict), "project", "admin")
    sensitive_config = field_access_control(
        EncryptedJSONField(
            default=dict,
            ignore_decrypt_errors=True,  # allows us to load previously unencrypted data
        ),
        "project",
        "admin",
    )
    repository_cache = models.JSONField(default=list, blank=True)
    repository_cache_updated_at = models.DateTimeField(null=True, blank=True)

    errors = models.TextField()

    # Meta
    created_at = models.DateTimeField(auto_now_add=True, blank=True)
    created_by = models.ForeignKey("User", on_delete=models.SET_NULL, null=True, blank=True)

    objects: IntegrationManager = IntegrationManager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "kind", "integration_id"], name="posthog_integration_kind_id_unique"
            )
        ]
        indexes = [models.Index(fields=["kind", "integration_id"], name="posthog_integration_kind_ext")]

    @property
    def display_name(self) -> str:
        if self.kind == "pinterest-ads":
            # Pinterest's OAuth username is an opaque hash, so prefer the business name when there is one.
            return self.config.get("business_name") or self.config.get("username") or self.integration_id
        if self.kind == "tiktok-ads":
            # The OAuth id is a list of advertiser ids, so prefer whoever authorized the connection.
            return self.config.get("user_email") or self.config.get("user_display_name") or self.integration_id
        # Deferred: every provider module imports `model` for the `Integration` type, so a
        # module-level import here would cycle back through them.
        from . import google_cloud, oauth  # noqa: PLC0415 — breaks a circular import

        if self.kind in oauth.OauthIntegration.supported_kinds:
            region = self.config.get("region") if self.kind == "posthog" else None
            oauth_config = oauth.OauthIntegration.oauth_config_for_kind(self.kind, region)
            return common.dot_get(self.config, oauth_config.name_path, self.integration_id)
        if self.kind in google_cloud.GoogleCloudIntegration.supported_kinds:
            return self.integration_id or "unknown ID"
        if self.kind == "github":
            return common.dot_get(self.config, "account.name", self.integration_id)
        if self.kind == "databricks":
            return self.integration_id or "unknown ID"
        if self.kind == Integration.IntegrationKind.AWS_S3:
            name = self.integration_id or "unknown ID"

            account_id = self.config.get("aws_account_id")
            role = self.config.get("aws_role_arn")

            if role:
                detail = f"AWS role '{role}'"
            elif account_id:
                detail = f"AWS account {account_id}"
            else:
                detail = "access key"

            return f"{name} ({detail})"
        if self.kind == Integration.IntegrationKind.AWS_REDSHIFT:
            name = self.integration_id or "unknown ID"

            account_id = self.config.get("aws_account_id")
            role = self.config.get("aws_role_arn")
            host = self.config.get("host")
            user = self.config.get("user")

            if role:
                detail = f"AWS role '{role}'"
            elif account_id:
                detail = f"AWS account {account_id}"
            elif user and host:
                detail = f"{user}@{host}"
            else:
                detail = "access key"

            return f"{name} ({detail})"
        if self.kind == Integration.IntegrationKind.S3_COMPATIBLE:
            name = self.integration_id or "unknown ID"
            endpoint_url = self.config.get("endpoint_url")
            detail = f"access key, {endpoint_url}" if endpoint_url else "access key"
            return f"{name} ({detail})"
        if self.kind == Integration.IntegrationKind.SNOWFLAKE:
            name = self.integration_id or "unknown ID"
            auth_type = self.config.get("authentication_type", "password")
            account = self.config.get("account")
            return f"{name} (account: {account}, {auth_type} auth)"
        if self.kind == "gitlab":
            return self.integration_id or "unknown ID"
        if self.kind == "email":
            return self.config.get("email", self.integration_id)
        if self.kind == "apns":
            return self.config.get("bundle_id", self.integration_id)

        return f"ID: {self.integration_id}"

    @property
    def access_token(self) -> str | None:
        return _decrypted_sensitive_value(self, "access_token")

    @property
    def refresh_token(self) -> str | None:
        return _decrypted_sensitive_value(self, "refresh_token")


def defer_repository_cache_fields(queryset: models.QuerySet[Integration]) -> models.QuerySet[Integration]:
    return queryset.defer("repository_cache", "repository_cache_updated_at")


@database_sync_to_async
def aget_integration_by_id(integration_id: str, team_id: int) -> Integration | None:
    return Integration.objects.get(id=integration_id, team_id=team_id)
