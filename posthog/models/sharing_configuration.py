import secrets
from datetime import timedelta
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from posthog.models.share_password import SharePassword
    from posthog.models.user import User

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.db import models, transaction
from django.utils import timezone

import structlog

from posthog.jwt import PosthogJwtAudience, encode_jwt

from products.product_analytics.backend.models.insight import Insight

logger = structlog.get_logger(__name__)


def get_default_access_token() -> str:
    return secrets.token_urlsafe(22)


class SharingConfiguration(models.Model):
    # Relations
    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    dashboard = models.ForeignKey("dashboards.Dashboard", on_delete=models.CASCADE, null=True)
    insight = models.ForeignKey("product_analytics.Insight", on_delete=models.CASCADE, null=True)
    recording = models.ForeignKey(
        "SessionRecording",
        related_name="sharing_configurations",
        on_delete=models.CASCADE,
        to_field="session_id",
        null=True,
        blank=True,
    )
    notebook = models.ForeignKey(
        "notebooks.Notebook",
        related_name="sharing_configurations",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    interviewee_context = models.ForeignKey(
        "user_interviews.IntervieweeContext",
        related_name="sharing_configurations",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True, blank=True)

    enabled = models.BooleanField(default=False)
    # db_constraint=False: an FK constraint to the hot posthog_user table would lock the parent
    # (HotTableAlterPolicy); db_index=False: only ever read through the instance, never queried by user.
    enabled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_constraint=False,
        db_index=False,
        related_name="+",
        help_text="Member who last enabled sharing; public-link queries execute with their access",
    )
    access_token = models.CharField(
        max_length=400,
        null=True,
        blank=True,
        default=get_default_access_token,
        unique=True,
    )

    expires_at = models.DateTimeField(
        null=True, blank=True, help_text="When this sharing configuration expires (null = active)"
    )

    settings = models.JSONField(null=True, blank=True, help_text="JSON settings for storing configuration options")

    password_required = models.BooleanField(default=False)

    @classmethod
    def shareable_resource_fields(cls) -> frozenset[str]:
        """The FK fields that point at a shareable resource - every relation except the team tenant FK
        and the enabled_by attribution FK.

        The sharing API cross-checks this against its per-resource edit-permission registry at import
        time, so a newly added shareable resource cannot ship without an explicit access-control decision.
        """
        return frozenset(
            field.name
            for field in cls._meta.fields
            if field.is_relation and field.many_to_one and field.name not in ("team", "enabled_by")
        )

    @classmethod
    def _resource_lookup(
        cls,
        *,
        team_id: int,
        dashboard: models.Model | None = None,
        insight: models.Model | None = None,
        recording: models.Model | None = None,
        notebook: models.Model | None = None,
        interviewee_context: models.Model | None = None,
    ) -> dict[str, Any]:
        return {
            "team_id": team_id,
            "dashboard": dashboard,
            "insight": insight,
            "recording": recording,
            "notebook": notebook,
            "interviewee_context": interviewee_context,
        }

    @classmethod
    def queryset_active_for_resource(cls, **resource_lookup: Any) -> models.QuerySet["SharingConfiguration"]:
        return cls.objects.filter(**resource_lookup, expires_at__isnull=True).order_by("-created_at")

    @classmethod
    def expire_duplicate_active_configs(
        cls,
        *,
        keep: "SharingConfiguration",
        duplicate_pks: list[int] | None = None,
        **resource_lookup: Any,
    ) -> int:
        duplicate_ids = duplicate_pks
        if duplicate_ids is None:
            duplicate_ids = list(
                cls.queryset_active_for_resource(**resource_lookup).exclude(pk=keep.pk).values_list("pk", flat=True)
            )
        if not duplicate_ids:
            return 0

        updated = cls.objects.filter(pk__in=duplicate_ids).update(expires_at=timezone.now())
        logger.warning(
            "sharing_configuration_duplicates_expired",
            kept_config_id=keep.pk,
            expired_config_ids=duplicate_ids,
            team_id=resource_lookup.get("team_id"),
        )
        return updated

    @classmethod
    def get_active_for_resource(cls, *, dedupe: bool = False, **resource_lookup: Any) -> "SharingConfiguration | None":
        if not dedupe:
            return cls.queryset_active_for_resource(**resource_lookup).first()

        with transaction.atomic():
            active_configs = list(cls.queryset_active_for_resource(**resource_lookup).select_for_update())
            if not active_configs:
                return None

            keep = active_configs[0]
            duplicate_pks = [config.pk for config in active_configs[1:]]
            if duplicate_pks:
                cls.expire_duplicate_active_configs(keep=keep, duplicate_pks=duplicate_pks, **resource_lookup)

            return keep

    def _lock_resource_for_rotation(self) -> None:
        # Resolve each parent model from its own FK instead of importing it. This keeps the module
        # free of product imports (``user_interviews`` only exposes its webhooks via tach's
        # ``[[interfaces]]``) and avoids cycling through ``posthog.models.team`` during ``Team``
        # initialization, since this module is loaded mid-init via product_analytics'
        # insight_caching_state.
        for field_name in ("dashboard", "insight", "notebook", "recording", "interviewee_context"):
            fk_value = getattr(self, f"{field_name}_id")
            if not fk_value:
                continue

            field = cast("models.ForeignKey", self._meta.get_field(field_name))
            related_model = cast("type[models.Model]", field.related_model)
            target_field_name = field.target_field.name
            related_model._default_manager.select_for_update().get(
                **{target_field_name: fk_value, "team_id": self.team_id}
            )
            return

    def _resource_lookup_for_instance(self) -> dict[str, Any]:
        return self._resource_lookup(
            team_id=self.team_id,
            dashboard=self.dashboard,
            insight=self.insight,
            recording=self.recording,
            notebook=self.notebook,
            interviewee_context=self.interviewee_context,
        )

    def rotate_access_token(self) -> "SharingConfiguration":
        """Create a new sharing configuration and expire the current one"""
        resource_lookup = self._resource_lookup_for_instance()

        with transaction.atomic():
            self._lock_resource_for_rotation()

            active_configs = list(
                SharingConfiguration.objects.select_for_update()
                .filter(**resource_lookup, expires_at__isnull=True)
                .order_by("-created_at")
            )

            if not active_configs:
                source = self
            else:
                source = active_configs[0]
                expire_at = timezone.now() + timedelta(seconds=settings.SHARING_TOKEN_GRACE_PERIOD_SECONDS)
                SharingConfiguration.objects.filter(pk__in=[config.pk for config in active_configs]).update(
                    expires_at=expire_at
                )

                if len(active_configs) > 1:
                    logger.warning(
                        "sharing_configuration_duplicates_expired_during_rotation",
                        kept_config_id=source.pk,
                        expired_config_ids=[config.pk for config in active_configs[1:]],
                        team_id=self.team_id,
                    )

            new_config = SharingConfiguration.objects.create(
                team=source.team,
                dashboard=source.dashboard,
                insight=source.insight,
                recording=source.recording,
                notebook=source.notebook,
                interviewee_context=source.interviewee_context,
                enabled=source.enabled,
                # Rotation is token hygiene, not a publish decision — the publisher stays the principal.
                enabled_by=source.enabled_by,
                settings=source.settings,
                password_required=source.password_required,
            )

            if source.password_required:
                from posthog.models.share_password import SharePassword

                for pw in source.share_passwords.filter(is_active=True):
                    SharePassword.objects.create(
                        sharing_configuration=new_config,
                        password_hash=pw.password_hash,
                        created_by=pw.created_by,
                        note=pw.note,
                        is_active=True,
                    )

        logger.info(
            "sharing_token_rotated",
            old_config_id=source.pk,
            new_config_id=new_config.pk,
            team_id=self.team_id,
        )

        return new_config

    def generate_password_protected_token(self, share_password: "SharePassword") -> str:
        """
        Generate a JWT token for password-protected sharing access.
        This token is time-limited and scoped to the specific SharePassword used for authentication.
        """
        if not self.password_required:
            raise ValueError("Cannot generate password-protected token for non-password-protected sharing")

        return encode_jwt(
            payload={
                "share_password_id": share_password.id,
                "team_id": self.team_id,
                "access_token": self.access_token,  # Include for validation
            },
            expiry_delta=timedelta(hours=24),  # 24-hour session duration
            audience=PosthogJwtAudience.SHARING_PASSWORD_PROTECTED,
        )

    def effective_execution_user(self) -> "User | None":
        """The principal that queries triggered by this share's public link execute as.

        Anonymous viewers run the underlying queries with the access of the member who last
        enabled sharing — publishing is the act that exposes the data, so the publisher's access
        governs the link. Revoking their access to e.g. an access-controlled warehouse table
        propagates to already-published links on their next refresh. Fail-closed: returns None
        for legacy shares (enabled before enabled_by existed) and when the publisher was deleted
        or deactivated.
        """
        try:
            user = self.enabled_by
        except ObjectDoesNotExist:
            # db_constraint=False on enabled_by: a raw delete of the user can leave a dangling id.
            return None
        if user is None or not user.is_active:
            return None
        return user

    def can_access_object(self, obj: models.Model):
        if obj.team_id != self.team_id:  # type: ignore
            return False

        if obj._meta.object_name == "Insight" and (self.dashboard or self.notebook):
            return cast(Insight, obj).id in self.get_connected_insight_ids()

        for comparison in [self.insight, self.dashboard, self.recording, self.notebook, self.interviewee_context]:
            if comparison and comparison == obj:
                return True

        return False

    def get_connected_insight_ids(self) -> list[int]:
        if self.insight:
            if self.insight.deleted:
                return []
            return [self.insight.id]
        elif self.dashboard:
            if self.dashboard.deleted:
                return []
            # Check whether this sharing configuration's dashboard contains this insight
            return list(self.dashboard.tiles.exclude(insight__deleted=True).values_list("insight__id", flat=True))
        elif self.notebook:
            # Recompute on every call so that edits to the notebook automatically grant/revoke access
            # to the insights it embeds. Mirrors dashboard semantics.
            from products.notebooks.backend.facade.content import extract_referenced_insight_short_ids

            if self.notebook.deleted:
                return []
            short_ids = extract_referenced_insight_short_ids(self.notebook.content)
            if not short_ids:
                return []
            return list(
                Insight.objects.filter(
                    team=self.team,
                    short_id__in=short_ids,
                    deleted=False,
                ).values_list("id", flat=True)
            )
        return []
