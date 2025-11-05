from django.core.exceptions import ValidationError
from django.db import models

from posthog.models.utils import CreatedMetaFields, UUIDModel


class SyntheticMonitor(CreatedMetaFields, UUIDModel):
    """
    Configuration for synthetic HTTP monitoring checks (uptime and latency).
    All check results are stored as events in ClickHouse.
    """

    class Region(models.TextChoices):
        """AWS regions available for synthetic monitoring checks"""

        US_EAST_1 = "us-east-1"  # US East (N. Virginia)
        US_WEST_2 = "us-west-2"  # US West (Oregon)
        EU_WEST_1 = "eu-west-1"  # EU West (Ireland)
        EU_CENTRAL_1 = "eu-central-1"  # EU Central (Frankfurt)
        AP_SOUTHEAST_1 = "ap-southeast-1"  # Asia Pacific (Singapore)
        AP_NORTHEAST_1 = "ap-northeast-1"  # Asia Pacific (Tokyo)

    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    name = models.CharField(max_length=400)

    # Check configuration
    url = models.URLField()
    frequency_minutes = models.IntegerField(
        choices=[(1, "1 minute"), (5, "5 minutes"), (15, "15 minutes"), (30, "30 minutes"), (60, "60 minutes")]
    )
    regions = models.JSONField(
        default=list,
        help_text="List of regions to run checks from (e.g., ['us-east-1', 'eu-west-1'])",
        choices=Region.choices,
    )

    # HTTP configuration
    method = models.CharField(max_length=10, default="GET")
    headers = models.JSONField(
        null=True, blank=True, help_text="Custom HTTP headers as JSON object (e.g., {'Authorization': 'Bearer ...'})"
    )
    body = models.TextField(null=True, blank=True, help_text="Request body for POST/PUT requests")
    expected_status_code = models.IntegerField(default=200)
    timeout_seconds = models.IntegerField(default=30)

    # Alerts are handled via HogFlows (workflows)
    # Users create workflows triggered by synthetic_http_check events

    # Monitor state
    enabled = models.BooleanField(default=True)

    created_by = models.ForeignKey("User", on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["team", "enabled"]),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        if self.method not in ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"]:
            raise ValidationError({"method": "Invalid HTTP method"})

        if self.expected_status_code < 100 or self.expected_status_code >= 600:
            raise ValidationError({"expected_status_code": "Status code must be between 100 and 599"})

        if self.regions and not isinstance(self.regions, list):
            raise ValidationError({"regions": "Regions must be a list"})
        if self.regions:
            valid_regions = {region.value for region in SyntheticMonitor.Region}
            invalid_regions = [r for r in self.regions if r not in valid_regions]
            if invalid_regions:
                raise ValidationError(
                    {
                        "regions": f"Invalid regions: {', '.join(invalid_regions)}. "
                        f"Valid regions are: {', '.join(sorted(valid_regions))}"
                    }
                )
