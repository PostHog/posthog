from django.db import models
from posthog.models.team import Team
from posthog.models.utils import UUIDModel, CreatedMetaFields


class Product(UUIDModel, CreatedMetaFields):
    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)
    name: models.CharField = models.CharField(max_length=200)
    description: models.TextField = models.TextField(blank=True)
    price: models.DecimalField = models.DecimalField(max_digits=19, decimal_places=4)
    currency: models.CharField = models.CharField(max_length=3, default="USD")

    class Meta:
        unique_together = ("team", "name")
