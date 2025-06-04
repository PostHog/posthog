from typing import TYPE_CHECKING

from django.db import models
import structlog

from posthog.models.utils import UUIDModel

if TYPE_CHECKING:
    pass

logger = structlog.get_logger(__name__)


class HogFlowInvocation(UUIDModel):
    """
    Stores the meta information on instances of running HogFlow
    """

    class Meta:
        indexes = [
            models.Index(fields=["hog_flow_id", "hog_flow_version", "team"]),
        ]

    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    hog_flow = models.ForeignKey("HogFlow", on_delete=models.CASCADE)
    hog_flow_version = models.IntegerField()
    variables = models.JSONField(default=dict)
    state = models.JSONField(default=dict)

    queue = models.CharField(max_length=100)
    queue_parameters = models.JSONField(default=dict)
    queue_priority = models.IntegerField(null=True, blank=True)
    queue_scheduled_at = models.DateTimeField(auto_now_add=True)
    queue_metadata = models.JSONField(default=dict)
    queue_source = models.CharField(max_length=20)

    def __str__(self):
        return f"HogFlowInvocation {self.id}: {self.hog_flow_id}/{self.hog_flow_version}"


class HogFlowInvocationResult(UUIDModel):
    """
    Stores the result of invoking a HogFlow
    """

    invocation = models.ForeignKey("HogFlowInvocation", on_delete=models.CASCADE)
    result = models.JSONField()

    def __str__(self):
        return f"HogFlowInvocationResult {self.id}: {self.invocation_id}"
