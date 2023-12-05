from django.db import models
from encrypted_fields.fields import EncryptedTextField

from posthog.models.team import Team
from posthog.models.utils import CreatedMetaFields, UUIDModel, sane_repr


class DataWarehouseCredential(CreatedMetaFields, UUIDModel):
    access_key: EncryptedTextField = EncryptedTextField(max_length=500)
    access_secret: EncryptedTextField = EncryptedTextField(max_length=500)
    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)

    __repr__ = sane_repr("access_key")
