from django.contrib.postgres.fields import ArrayField
from django.db import models


class Element(models.Model):
    USEFUL_ELEMENTS = ["a", "button", "input", "select", "textarea", "label"]
    text: models.CharField = models.CharField(max_length=10_000, null=True, blank=True)
    tag_name: models.CharField = models.CharField(max_length=1_000, null=True, blank=True)
    href: models.CharField = models.CharField(max_length=10_000, null=True, blank=True)
    attr_id: models.CharField = models.CharField(max_length=10_000, null=True, blank=True)
    attr_class = ArrayField(models.CharField(max_length=200, blank=True), null=True, blank=True)
    nth_child: models.IntegerField = models.IntegerField(null=True, blank=True)
    nth_of_type: models.IntegerField = models.IntegerField(null=True, blank=True)
    attributes: models.JSONField = models.JSONField(default=dict)
    event: models.ForeignKey = models.ForeignKey("Event", on_delete=models.CASCADE, null=True, blank=True)
    order: models.IntegerField = models.IntegerField(null=True, blank=True)
    group: models.ForeignKey = models.ForeignKey("ElementGroup", on_delete=models.CASCADE, null=True, blank=True)
