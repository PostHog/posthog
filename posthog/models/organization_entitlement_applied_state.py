from django.db import models


class OrganizationEntitlementAppliedState(models.Model):
    # Avoid a migration lock on the hot organization table; Django still cascades deletes.
    organization = models.ForeignKey(
        "posthog.Organization", on_delete=models.CASCADE, db_constraint=False, related_name="+"
    )
    reactor_key = models.CharField(max_length=200)
    snapshot = models.JSONField(default=list)
    applied_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "reactor_key"], name="organization_entitlement_reactor_unique"
            )
        ]
