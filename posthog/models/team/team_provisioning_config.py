import logging

from django.db import models

from posthog.models.team.extensions import register_team_extension_signal

logger = logging.getLogger(__name__)


class TeamProvisioningConfig(models.Model):
    team = models.OneToOneField("posthog.Team", on_delete=models.CASCADE, primary_key=True)

    # The OAuth application that provisioned this team. Bound to the issuing
    # partner so resource endpoints can verify that the bearer token's app owns
    # the team before auto-adding it to scope. Null for rows created before the
    # field was added; legacy rows are not auto-add eligible.
    application = models.ForeignKey(
        "posthog.OAuthApplication",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="provisioned_team_configs",
    )

    stripe_project_id = models.CharField(max_length=255, null=True, blank=True, unique=True)
    service_id = models.CharField(max_length=255, default="analytics")

    # Null for rows that pre-date the field. Together with `application` this backs the
    # durable daily ceiling on partner account creation: a Postgres count of rows the
    # partner created in the last day, which stays correct when the Redis rate-limit
    # buckets are evicted or unavailable.
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["application"], name="tpc_application_idx"),
            models.Index(fields=["application", "created_at"], name="tpc_application_created_idx"),
        ]


register_team_extension_signal(TeamProvisioningConfig, logger=logger)
