from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

MAX_EVENTS_RETENTION_SETTING_MONTHS = 84


class OrganizationEventsRetentionSetting(models.Model):
    """The events retention window an organization admin chose. An organization with no row follows its plan."""

    # db_constraint=False: a real FK constraint would lock posthog_organization (a hot table) while migrating.
    organization = models.OneToOneField(
        "posthog.Organization", on_delete=models.CASCADE, primary_key=True, db_constraint=False, related_name="+"
    )
    retention_months = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(MAX_EVENTS_RETENTION_SETTING_MONTHS)]
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(retention_months__gte=1)
                & models.Q(retention_months__lte=MAX_EVENTS_RETENTION_SETTING_MONTHS),
                name="org_events_retention_setting_months_range",
            )
        ]
