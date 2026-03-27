from __future__ import annotations

from typing import Any

from django.db import models

from posthog.models.resource_transfer.visitors.base import ResourceTransferVisitor


class EarlyAccessFeatureVisitor(
    ResourceTransferVisitor,
    kind="EarlyAccessFeature",
    excluded_fields=["created_at"],
    friendly_name="Early access feature",
):
    @classmethod
    def get_model(cls) -> type[models.Model]:
        from products.early_access_features.backend.models import EarlyAccessFeature

        return EarlyAccessFeature

    @classmethod
    def get_display_name(cls, resource: Any) -> str:
        return str(resource.name) if getattr(resource, "name", None) else super().get_display_name(resource)
