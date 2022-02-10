from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import ugettext_lazy as _

from posthog.models.utils import UUIDModel


class Tag(UUIDModel):
    name: models.SlugField = models.CharField(max_length=255)
    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)

    class Meta:
        unique_together = ("name", "team")

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        """
        Ensure that tag doesn't have whitespace
        """
        if " " in self.name:
            raise ValidationError({"name": _(f"Tag name '{self.name}' must not have whitespace.")}, code="invalid")

    def save(self, *args, **kwargs):
        # Verify slug is correctly formatted before saving.
        self.full_clean()
        return super(Tag, self).save(*args, **kwargs)
