from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class MetricRunCount(TeamScopedRootMixin, UUIDModel):
    """How many times a metric ran on one UTC day, from one request source.

    A Postgres counter, not a query over analytics events: the catalog list reads it for every
    row, and the server-side run events go to PostHog's own project, not the customer's.
    """

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    metric = models.ForeignKey("data_catalog.Metric", on_delete=models.CASCADE, related_name="+")
    date = models.DateField(help_text="UTC day of the runs.")
    source = models.CharField(
        max_length=32,
        help_text="The surface that sent the run request (an EventSource value such as web, api, mcp or "
        "posthog_ai), or 'internal' for a run with no request.",
    )
    count = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["metric", "date", "source"],
                name="unique_metric_run_count_per_day_and_source",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.metric_id} {self.date} {self.source}: {self.count}"
