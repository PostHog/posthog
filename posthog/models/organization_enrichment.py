from django.db import models

from posthog.models.organization import Organization
from posthog.models.utils import UUIDModel


class OrganizationEnrichment(UUIDModel):
    # db_constraint=False keeps CreateModel off posthog_organization's lock path (hot table)
    organization = models.OneToOneField(
        Organization, on_delete=models.CASCADE, db_constraint=False, related_name="enrichment_record"
    )
    # Namespaced deterministic enrichment signals, e.g. company_type_deterministic
    data = models.JSONField(default=dict)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
