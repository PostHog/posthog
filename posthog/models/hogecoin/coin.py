from posthog.models.utils import UUIDModel
from django.db import models


class HogeCoinWallet(UUIDModel):
    user = models.ForeignKey("User", on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    balance = models.BigIntegerField(default=0)
