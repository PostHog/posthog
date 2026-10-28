"""The Integration Django model, its manager, and generic secret-decryption helpers."""

from collections.abc import Iterable, Mapping
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
from .auth_types import (
    AuthRequirement,
    AuthTypeSelector,
    IntegrationAuthType,
    catalogued_kinds,
    config_for_write,
    default_auth_type,
    effective_auth_type,
    normalized_config,
    rows_with_default_auth_type_q,
)

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


# Marks a row that a data warehouse source created from the fields a user typed in. The value is the
# source type, so a client can show the source's name and icon for a kind it does not know. The row
# holds `sensitive_config["fields"]` in the source's own field shape, not in the shape that other
# code of the kind reads. Hog functions must never get such a row as an input.
WAREHOUSE_SOURCE_TYPE_CONFIG_KEY = "warehouse_source_type"


class IntegrationQuerySet(models.QuerySet["Integration"]):
    # Set by `with_auth`. None means the query did not state its auth types.
    _auth_requirement: AuthRequirement | None = None
    # True on the queryset that `Integration.objects` returns without `with_auth`. It holds only
    # rows with the default auth type of their kind, so code that does not state its auth types
    # never gets a row it cannot handle.
    _implicit_default_auth: bool = False

    def _clone(self) -> Self:
        clone = super()._clone()
        clone._auth_requirement = self._auth_requirement
        clone._implicit_default_auth = self._implicit_default_auth
        return clone

    def with_auth(self, *auth_types: IntegrationAuthType | AuthTypeSelector | str) -> Self:
        """Keep only the rows whose auth type is in `auth_types`.

        Pass `DEFAULT` for the default auth type of each row's kind, or `ANY` for every row. A row
        without `config["auth_type"]` has the default auth type of its kind. A create through a
        `with_auth` with one non-default auth type writes it into `config["auth_type"]`.
        """
        if self._implicit_default_auth:
            raise ValueError(
                "Call with_auth() directly on Integration.objects. The queryset without it holds only rows "
                "with the default auth type of their kind."
            )
        requirement = AuthRequirement.of(*auth_types)
        queryset = self._chain() if requirement.any else self.filter(requirement.q())
        queryset._auth_requirement = requirement
        return queryset

    def _with_implicit_default_auth(self) -> Self:
        queryset = self.filter(rows_with_default_auth_type_q())
        queryset._implicit_default_auth = True
        return queryset

    def _write_requirement(self) -> AuthRequirement | None:
        if self._auth_requirement is not None:
            return self._auth_requirement
        return AuthRequirement.kind_default_only() if self._implicit_default_auth else None

    def _with_config_for_write(self, values: dict[str, Any], kind: Any) -> dict[str, Any]:
        requirement = self._write_requirement()
        if requirement is None:
            return values
        return {**values, "config": config_for_write(kind, values.get("config"), requirement)}

    def create(self, **kwargs: Any) -> "Integration":
        return super().create(**self._with_config_for_write(kwargs, kwargs.get("kind")))

    def bulk_create(self, objs: Iterable["Integration"], *args: Any, **kwargs: Any) -> list["Integration"]:
        objs = list(objs)
        requirement = self._write_requirement()
        for obj in objs:
            if requirement is not None:
                obj.config = config_for_write(obj.kind, obj.config, requirement)
            # bulk_create does not call save(), so normalize here too.
            obj.config = normalized_config(obj.kind, obj.config)
        return super().bulk_create(objs, *args, **kwargs)

    def update_or_create(
        self,
        defaults: Mapping[str, Any] | None = None,
        create_defaults: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> tuple["Integration", bool]:
        # The update path sets `config` from `defaults` on the row it found. Without this, a new
        # config without the key would turn a typed-in row back into a default row.
        kind = kwargs.get("kind") or (defaults or {}).get("kind") or (create_defaults or {}).get("kind")
        if defaults is not None and "config" in defaults:
            defaults = self._with_config_for_write(dict(defaults), kind)
        return super().update_or_create(defaults=defaults, create_defaults=create_defaults, **kwargs)

    def holding_warehouse_source_fields(self) -> Self:
        return self.filter(config__has_key=WAREHOUSE_SOURCE_TYPE_CONFIG_KEY)

    def without_warehouse_source_fields(self) -> Self:
        return self.exclude(config__has_key=WAREHOUSE_SOURCE_TYPE_CONFIG_KEY)

    def for_github_installation_id(self, installation_id: str | int) -> Self:
        return self.filter(
            Q(config__installation_id=str(installation_id)) | Q(config__installation_id=int(installation_id))
        )


class IntegrationManager(models.Manager["Integration"]):
    _queryset_class = IntegrationQuerySet

    def get_queryset(self) -> IntegrationQuerySet:
        queryset = IntegrationQuerySet(self.model, using=self._db, hints=self._hints)
        if self._is_related_manager():
            return queryset
        return queryset._with_implicit_default_auth()

    def with_auth(self, *auth_types: IntegrationAuthType | AuthTypeSelector | str) -> IntegrationQuerySet:
        if self._is_related_manager():
            return self.get_queryset().with_auth(*auth_types)
        return IntegrationQuerySet(self.model, using=self._db, hints=self._hints).with_auth(*auth_types)

    def filter(self, *args: Any, **kwargs: Any) -> IntegrationQuerySet:
        return self.get_queryset().filter(*args, **kwargs)

    def _is_related_manager(self) -> bool:
        # Django builds related managers such as `team.integration_set` as subclasses of this class,
        # and only they have `core_filters`. They stay unfiltered, the same as the base manager that
        # cascades, `save()` and `refresh_from_db()` use.
        return hasattr(self, "core_filters")

    def first_github_for_team_installation(self, team_id: int, installation_id: str) -> "Integration | None":
        return (
            self.with_auth(IntegrationAuthType.APP)
            .filter(team_id=team_id, kind=Integration.IntegrationKind.GITHUB)
            .for_github_installation_id(installation_id)
            .first()
        )

    def first_github_for_user_installation(self, user: User, installation_id: str) -> "Integration | None":
        user_team_ids = user.teams.values_list("id", flat=True)
        return (
            self.with_auth(IntegrationAuthType.APP)
            .filter(team_id__in=user_team_ids, kind=Integration.IntegrationKind.GITHUB)
            .for_github_installation_id(installation_id)
            .first()
        )


def integration_kind_choices() -> list[tuple[str, str | Promise]]:
    # Callable so growing the enum doesn't generate a no-op migration. Kinds that a product registers
    # with `register_kind_auth_types` (the warehouse source credential kinds) are valid stored kinds
    # too, but they stay out of `IntegrationKind` and so out of the public API enum.
    choices: list[tuple[str, str | Promise]] = list(Integration.IntegrationKind.choices)
    known = {value for value, _ in choices}
    choices += [(kind, kind) for kind in sorted(catalogued_kinds()) if kind not in known]
    return choices


class Integration(models.Model):
    AuthType = IntegrationAuthType

    class IntegrationKind(models.TextChoices):
        ANTHROPIC = "anthropic"
        APPLE_ADS = "apple-ads"
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
        HELPSCOUT = "helpscout"
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
        TWITTER_ADS = "twitter-ads"
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

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.config = normalized_config(self.kind, self.config)
        super().save(*args, **kwargs)

    @property
    def auth_type(self) -> str:
        """The stored `config["auth_type"]`, or the default auth type of the kind when the key is missing."""
        return effective_auth_type(self.kind, self.config)

    @property
    def holds_warehouse_source_fields(self) -> bool:
        return isinstance(self.config, dict) and WAREHOUSE_SOURCE_TYPE_CONFIG_KEY in self.config

    @property
    def display_name(self) -> str:
        if self.holds_warehouse_source_fields or self.auth_type != default_auth_type(self.kind):
            # The branches below read the config shape of the default auth type.
            return self.config.get("display_name") or f"ID: {self.integration_id}"
        if self.kind == "twitter-ads":
            return self.config.get("screen_name") or self.integration_id
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
            name = self.config.get("bundle_id", self.integration_id)
            return f"{name} (sandbox)" if self.config.get("environment") == "sandbox" else name
        if self.kind == Integration.IntegrationKind.POSTGRESQL:
            # The derived id reads as "1-db.example.com-5432-postgres", so prefer a name the
            # user chose. Falls back to host and user, which still beats the raw id.
            if name := self.config.get("name"):
                return name
            host = self.config.get("host")
            user = self.config.get("user")
            return f"{user}@{host}" if user and host else f"ID: {self.integration_id}"

        return f"ID: {self.integration_id}"

    def can_be_managed_by_creator(self, user_id: int | None) -> bool:
        return (
            user_id is not None and self.kind == self.IntegrationKind.GOOGLE_CALENDAR and self.created_by_id == user_id
        )

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


# The kinds that an API request can name. A kind that a product registers (a warehouse source
# credential kind) is stored data only, so the generated API enum stays small.
PUBLIC_INTEGRATION_KIND_CHOICES = list(Integration.IntegrationKind.choices)
