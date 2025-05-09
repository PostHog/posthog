from django.db import models
from django.utils import timezone
from typing import Dict, Any, Optional, List, Tuple

from posthog.models.organization import Organization


class ResourceType(models.TextChoices):
    EVENTS = "events", "Events"
    EXCEPTIONS = "exceptions", "Exceptions"
    RECORDINGS = "recordings", "Recordings"
    ROWS_SYNCED = "rows_synced", "Rows Synced"
    FEATURE_FLAG_REQUESTS = "feature_flag_requests", "Feature Flag Requests"
    API_QUERIES_READ_BYTES = "api_queries_read_bytes", "API Queries Read Bytes"


class OrganizationResourceUsage(models.Model):
    organization = models.ForeignKey(
        Organization, 
        on_delete=models.CASCADE, 
        related_name="resource_usages"
    )
    resource_type = models.CharField(
        max_length=64,
        choices=ResourceType.choices
    )
    
    # From billing
    limit = models.BigIntegerField(null=True)
    usage = models.BigIntegerField(default=0)
    
    # Local tracking
    todays_usage = models.BigIntegerField(default=0)
    quota_limited_until = models.IntegerField(null=True)  # Unix timestamp
    quota_limiting_suspended_until = models.IntegerField(null=True)  # Unix timestamp
    
    # Period
    period_start = models.DateTimeField(null=True)
    period_end = models.DateTimeField(null=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ("organization", "resource_type")
        indexes = [
            models.Index(fields=["organization", "resource_type"]),
        ]
        verbose_name = "Organization Resource Usage"
        verbose_name_plural = "Organization Resource Usages"

    def __str__(self) -> str:
        return f"{self.organization.name} - {self.resource_type}"


def get_organization_usage_info(organization: Organization) -> dict:
    """Convert OrganizationResourceUsage models to the legacy usage dict format"""
    usage_dict = {}
    
    # Get all resource usages for this organization
    resource_usages = OrganizationResourceUsage.objects.filter(organization=organization)
    
    # Build the period from the first resource that has it
    period = None
    for resource in resource_usages:
        if resource.period_start and resource.period_end:
            period = [resource.period_start.isoformat(), resource.period_end.isoformat()]
            break
    
    # Add each resource to the dict
    for resource in resource_usages:
        usage_dict[resource.resource_type] = {
            "usage": resource.usage,
            "limit": resource.limit,
            "todays_usage": resource.todays_usage,
        }
        
        if resource.quota_limited_until:
            usage_dict[resource.resource_type]["quota_limited_until"] = resource.quota_limited_until
            
        if resource.quota_limiting_suspended_until:
            usage_dict[resource.resource_type]["quota_limiting_suspended_until"] = resource.quota_limiting_suspended_until
    
    if period:
        usage_dict["period"] = period
        
    return usage_dict


def update_organization_usage_from_dict(organization: Organization, usage_dict: dict) -> None:
    """Update OrganizationResourceUsage models from a usage dict"""
    if not usage_dict:
        return
        
    period_start = None
    period_end = None
    
    if "period" in usage_dict:
        try:
            from dateutil import parser
            period_start = parser.parse(usage_dict["period"][0])
            period_end = parser.parse(usage_dict["period"][1])
        except (IndexError, ValueError, TypeError):
            pass
    
    for resource_type, resource_data in usage_dict.items():
        if resource_type == "period":
            continue
            
        # Skip if not a dictionary (period is a list)
        if not isinstance(resource_data, dict):
            continue
            
        # Get or create the resource usage
        resource_usage, created = OrganizationResourceUsage.objects.get_or_create(
            organization=organization,
            resource_type=resource_type,
            defaults={
                "limit": resource_data.get("limit"),
                "usage": resource_data.get("usage", 0),
                "todays_usage": resource_data.get("todays_usage", 0),
                "quota_limited_until": resource_data.get("quota_limited_until"),
                "quota_limiting_suspended_until": resource_data.get("quota_limiting_suspended_until"),
                "period_start": period_start,
                "period_end": period_end,
            }
        )
        
        if not created:
            # Update existing resource usage
            resource_usage.limit = resource_data.get("limit")
            resource_usage.usage = resource_data.get("usage", 0)
            resource_usage.todays_usage = resource_data.get("todays_usage", 0)
            resource_usage.quota_limited_until = resource_data.get("quota_limited_until")
            resource_usage.quota_limiting_suspended_until = resource_data.get("quota_limiting_suspended_until")
            resource_usage.period_start = period_start
            resource_usage.period_end = period_end
            resource_usage.save()
