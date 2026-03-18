from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from django.db import models

ResourceKind = Literal["Action", "Cohort", "Dashboard", "DashboardTile", "Insight", "Text", "Team", "Project", "User"]
ResourceTransferKey = tuple[ResourceKind, Any]  # tuple of (kind, primary key)
ResourcePayload = dict[str, Any]
ResourceMap = dict[ResourceTransferKey, "ResourceTransferVertex"]
RewriteRelationFn = Callable[
    [ResourcePayload, ResourceMap], ResourcePayload
]  # (payload, edge, resource_map) -> payload


@dataclass
class ResourceTransferEdge:
    name: str
    target_model: type[models.Model]
    target_primary_key: Any
    rewrite_relation: RewriteRelationFn  # function that the takes in the parameters to create the resource and returns the parameters with the foreign key substituted

    @property
    def key(self) -> ResourceTransferKey:
        from posthog.models.resource_transfer.visitors import ResourceTransferVisitor

        visitor = ResourceTransferVisitor.get_visitor(self.target_model)

        if visitor is None:
            raise TypeError(f"Model has no configured visitor: {self.target_model.__name__}")

        return (visitor.kind, self.target_primary_key)


@dataclass
class ResourceTransferVertex:
    model: type
    primary_key: Any
    source_resource: models.Model
    edges: list[ResourceTransferEdge]
    duplicated_resource: models.Model | None = None

    @property
    def key(self) -> ResourceTransferKey:
        from posthog.models.resource_transfer.visitors import ResourceTransferVisitor

        visitor = ResourceTransferVisitor.get_visitor(self.model)

        if visitor is None:
            raise TypeError(f"Model has no configured visitor: {self.model.__name__}")

        return (visitor.kind, self.primary_key)
