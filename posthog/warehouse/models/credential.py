from posthog.models.utils import UUIDModel, CreatedMetaFields, sane_repr
from django.db import models
from posthog.models.team import Team
from encrypted_fields.fields import EncryptedTextField


class DataWarehouseCredential(CreatedMetaFields, UUIDModel):
    access_key: EncryptedTextField = EncryptedTextField(max_length=500)
    access_secret: EncryptedTextField = EncryptedTextField(max_length=500)
    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)

    __repr__ = sane_repr("access_key")
