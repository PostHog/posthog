from django.db import models

from .utils import UUIDT


class BaseModel(models.Model):
    """
    Abstract BaseModel with basic shared functionality.
    """

    id: models.UUIDField = models.UUIDField(primary_key=True, default=UUIDT, editable=False)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True, editable=False)
    updated_at: models.DateTimeField = models.DateTimeField(auto_now=True, editable=False)

    class Meta:
        abstract = True
