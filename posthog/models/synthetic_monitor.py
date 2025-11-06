from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel

# Valid AWS regions for synthetic monitoring
VALID_REGIONS = {
    "us-east-1",  # US East (N. Virginia)
    "us-west-2",  # US West (Oregon)
    "eu-west-1",  # EU West (Ireland)
    "eu-central-1",  # EU Central (Frankfurt)
    "ap-southeast-1",  # Asia Pacific (Singapore)
    "ap-northeast-1",  # Asia Pacific (Tokyo)
}


def validate_regions(value):
    """Validate that regions is a list of valid AWS region values"""
    if not isinstance(value, list):
        raise ValidationError("Regions must be a list")

    if len(value) == 0:
        return

    invalid_regions = [r for r in value if r not in VALID_REGIONS]

    if invalid_regions:
        raise ValidationError(
            f"Invalid regions: {', '.join(invalid_regions)}. Valid regions are: {', '.join(sorted(VALID_REGIONS))}"
        )


class SyntheticMonitor(CreatedMetaFields, UpdatedMetaFields, UUIDModel):
    """
    Configuration for synthetic HTTP monitoring checks (uptime and latency).
    All check results are stored as events in ClickHouse.
    """

    class Method(models.TextChoices):
        """HTTP methods available for synthetic monitoring checks"""

        GET = "GET"
        POST = "POST"
        PUT = "PUT"
        PATCH = "PATCH"
        DELETE = "DELETE"
        HEAD = "HEAD"

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
        validators=[validate_regions],
    )

    # HTTP configuration
    method = models.CharField(
        max_length=10,
        choices=Method.choices,
        default=Method.GET,
    )
    headers = models.JSONField(
        null=True, blank=True, help_text="Custom HTTP headers as JSON object (e.g., {'Authorization': 'Bearer ...'})"
    )
    body = models.TextField(null=True, blank=True, help_text="Request body for POST/PUT requests")
    expected_status_code = models.IntegerField(
        default=200,
        validators=[MinValueValidator(100), MaxValueValidator(599)],
    )
    timeout_seconds = models.IntegerField(default=30)
    enabled = models.BooleanField(default=True)

    class Meta:
        indexes = [
            models.Index(fields=["team", "enabled"]),
        ]

    def __str__(self):
        return self.name
