from django.db import models


class ServiceAccountState(models.Model):
    user = models.OneToOneField(
        "posthog.User",
        primary_key=True,
        related_name="service_account_state",
        on_delete=models.CASCADE,
        db_constraint=False,
    )
    organization = models.ForeignKey(
        "posthog.Organization", related_name="service_account_states", on_delete=models.CASCADE, db_constraint=False
    )
    deleted_at = models.DateTimeField(null=True, blank=True)
