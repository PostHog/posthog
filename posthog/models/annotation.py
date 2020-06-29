from django.db import models
from django.utils.translation import gettext_lazy as _

class Annotation(models.Model):

    class CreationType(models.TextChoices):
        USER = 'USR', _('User')
        GITHUB = 'GIT', _('Github')

    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    content: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    created_at: models.DateTimeField = models.DateTimeField(
        null=True, blank=True
    )
    updated_at: models.DateTimeField = models.DateTimeField(
        auto_now=True
    )
    dashboard_item: models.ForeignKey = models.ForeignKey(
        "DashboardItem", on_delete=models.SET_NULL, null=True, blank=True
    )
    created_by: models.ForeignKey = models.ForeignKey(
        "User", on_delete=models.SET_NULL, null=True, blank=True
    )
    creation_type = models.CharField(
        max_length=3,
        choices=CreationType.choices,
        default=CreationType.USER,
    )
    date_marker: models.DateTimeField = models.DateTimeField(null=True, blank=True)

    apply_all: models.BooleanField = models.BooleanField(default=False)
    deleted: models.BooleanField = models.BooleanField(default=False)
