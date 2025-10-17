from django.db import models

from posthog.helpers.encrypted_fields import EncryptedTextField
from posthog.models.team import Team
from posthog.models.utils import CreatedMetaFields, UUIDTModel, sane_repr
from posthog.sync import database_sync_to_async


class DataWarehouseCredential(CreatedMetaFields, UUIDTModel):
    access_key = EncryptedTextField(max_length=500)
    access_secret = EncryptedTextField(max_length=500)
    team = models.ForeignKey(Team, on_delete=models.CASCADE)

    __repr__ = sane_repr("access_key")


@database_sync_to_async
def aget_or_create_datawarehouse_credential(team_id, access_key, access_secret) -> DataWarehouseCredential:
    return get_or_create_datawarehouse_credential(team_id, access_key, access_secret)


def get_or_create_datawarehouse_credential(team_id, access_key, access_secret) -> DataWarehouseCredential:
    credential, _ = DataWarehouseCredential.objects.get_or_create(
        team_id=team_id, access_key=access_key, access_secret=access_secret
    )

    return credential
