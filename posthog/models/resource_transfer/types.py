from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from django.db import models

ResourceKind = Literal["Action", "Cohort", "Dashboard", "DashboardTile", "Insight", "Text", "Team", "Project", "User"]
ResourceTransferKey = tuple[type, Any]  # tuple of (model type, primary key)
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
        return (self.target_model, self.target_primary_key)


@dataclass
class ResourceTransferVertex:
    model: type
    primary_key: Any
    source_resource: models.Model
    edges: list[ResourceTransferEdge]
    duplicated_resource: models.Model | None = None

    @property
    def key(self) -> ResourceTransferKey:
        return (self.model, self.primary_key)
