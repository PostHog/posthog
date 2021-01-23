from django.contrib.postgres.fields import JSONField
from django.db import models


class ActionStep(models.Model):
    CONTAINS = "contains"
    REGEX = "regex"
    EXACT = "exact"
    URL_MATCHING = [
        (CONTAINS, CONTAINS),
        (REGEX, REGEX),
        (EXACT, EXACT),
    ]
    action: models.ForeignKey = models.ForeignKey("Action", related_name="steps", on_delete=models.CASCADE)
    tag_name: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    text: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    href: models.CharField = models.CharField(max_length=65535, null=True, blank=True)
    selector: models.CharField = models.CharField(max_length=65535, null=True, blank=True)
    url: models.CharField = models.CharField(max_length=65535, null=True, blank=True)
    url_matching: models.CharField = models.CharField(
        max_length=400, choices=URL_MATCHING, default=CONTAINS, null=True, blank=True,
    )
    name: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    event: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    properties: JSONField = JSONField(default=list, null=True, blank=True)
