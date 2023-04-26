from posthog.models.utils import UUIDModel, CreatedMetaFields, sane_repr
from posthog.models.organization import Organization
from posthog.models.team import Team
from django.db import models
from django.core.exceptions import ValidationError


class WarehouseCluster(CreatedMetaFields, UUIDModel):
    name: models.CharField = models.CharField(max_length=500, default="default")
    organization: models.ForeignKey = models.ForeignKey(Organization, on_delete=models.CASCADE)
    write_node: models.ForeignKey = models.ForeignKey(
        "WarehouseNode", on_delete=models.DO_NOTHING, null=True, blank=True, related_name="write_node"
    )

    _is_cleaned = False

    def clean(self):
        # You can't do cross-table constraints in Postgres
        # Using clean so that Django Admin displays useful error messages
        self._is_cleaned = True
        if self.write_node and self.write_node.is_read_only:
            raise ValidationError("Cannot set write node to a read only node")
        super(WarehouseCluster, self).clean()

    def save(self, *args, **kwargs):
        if not self._is_cleaned:
            self.full_clean()
        self._is_cleaned = False
        super(WarehouseCluster, self).save(*args, **kwargs)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "name"], name="unique_cluster_name_per_organization")
        ]

    __repr__ = sane_repr("name", "organization")


class WarehouseClusterUser(UUIDModel, CreatedMetaFields):
    cluster: models.ForeignKey = models.ForeignKey(WarehouseCluster, on_delete=models.CASCADE)
    username: models.CharField = models.CharField(max_length=500, default="default")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["cluster", "username"], name="unique_username_per_cluster")]


class WarehouseClusterTeam(UUIDModel):
    cluster: models.ForeignKey = models.ForeignKey(WarehouseCluster, on_delete=models.CASCADE)
    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)
    is_read_cluster: models.BooleanField = models.BooleanField(default=False)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            # We can only read from one cluster at a time
            models.UniqueConstraint(
                fields=["team", "is_read_cluster"],
                condition=models.Q(is_read_cluster=True),
                name="one_read_cluster_per_team",
            ),
        ]
