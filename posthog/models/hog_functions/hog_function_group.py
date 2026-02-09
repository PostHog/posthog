from django.db import models
from posthog.models.utils import UUIDTModel

class HogFunctionGroup(UUIDTModel):
    class Meta:
        unique_together = ("team", "name")

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    name = models.CharField(max_length=400)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"HogFunctionGroup {self.id}: {self.name}"
