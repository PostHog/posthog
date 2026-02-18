from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING, Any

from django.db import models
from django.db.models import query_utils
from django.db.models.fields import related_descriptors

from posthog.models.resource_transfer.types import ResourceKind, ResourceTransferEdge
from posthog.models.utils import UUIDTClassicModel

if TYPE_CHECKING:
    from posthog.models import Team


class ResourceTransferVisitor:
    __VISITORS: list[type[ResourceTransferVisitor]] = []

    kind: ResourceKind
    excluded_fields: list[str]
    immutable: bool
    friendly_name: str
    user_facing: bool

    def __init_subclass__(
        cls,
        kind: ResourceKind,
        excluded_fields: list[str] | None = None,
        immutable: bool = False,
        friendly_name: str | None = None,
        user_facing: bool = True,
    ) -> None:
        cls.kind = kind
        cls.excluded_fields = excluded_fields or []
        cls.immutable = immutable
        cls.friendly_name = friendly_name if friendly_name is not None else kind
        cls.user_facing = user_facing

        ResourceTransferVisitor.__VISITORS.append(cls)

    @classmethod
    @abstractmethod
    def get_model(cls) -> type[models.Model]:
        """
        Subclasses should override this function to define the model which backs the resource kind.
        """

    @classmethod
    def get_dynamic_edges(cls, resource: Any) -> list[ResourceTransferEdge]:
        """
        Override to return extra edges at runtime. This is useful for schemas where foreign keys might be stored in untyped columns like JSON.
        """
        return []

    @classmethod
    def get_display_name(cls, resource: Any) -> str:
        """
        Return a human-readable name for a resource instance. Override in subclasses for custom behavior.
        Falls back to the resource's `name` attribute if present, otherwise uses kind + pk.
        """
        if hasattr(resource, "name") and resource.name:
            return str(resource.name)
        return f"{cls.kind} {resource.pk}"

    @classmethod
    def get_resource_team(cls, resource: Any) -> Team:
        """
        Return the team that owns a resource instance. Most resources have a `team` foreign key;
        override in subclasses for models where ownership is determined differently.
        """
        return resource.team

    @staticmethod
    def get_visitor(kind_or_value: ResourceKind | Any) -> type[ResourceTransferVisitor] | None:
        if isinstance(kind_or_value, str):
            return next(
                (visitor for visitor in ResourceTransferVisitor.__VISITORS if visitor.kind == kind_or_value), None
            )

        if isinstance(kind_or_value, type):
            return next(
                (visitor for visitor in ResourceTransferVisitor.__VISITORS if visitor.get_model() is kind_or_value),
                None,
            )

        return next(
            (visitor for visitor in ResourceTransferVisitor.__VISITORS if visitor.get_model() is type(kind_or_value)),
            None,
        )

    @classmethod
    def should_touch_field(cls, field_name: str) -> bool:
        # ignore private fields
        if field_name.startswith("_"):
            return False

        # ignore excluded fields
        if field_name in cls.excluded_fields:
            return False

        if cls.is_primary_key(field_name):
            return False

        if issubclass(cls.get_model(), UUIDTClassicModel) and field_name == "uuid":
            # UUIDTClassicModel adds a unique uuid column that is not a primary key and can break stuff
            return False

        # ignore fields that aren't a django model field
        class_attr = getattr(cls.get_model(), field_name)

        if (
            isinstance(class_attr, query_utils.DeferredAttribute)
            and not isinstance(
                class_attr,
                related_descriptors.ForeignKeyDeferredAttribute,  # ForeignKeyDeferredAttribute is used for fields that are automatically added to models as a part of a ForeignKeyField. we skip this to ensure we don't accidentally copy old relations
            )
        ):
            # it is a simple primitive column (not a relation)
            return True

        # it is a relation which is a more complicated scenario
        return isinstance(
            class_attr,
            (
                related_descriptors.ForwardManyToOneDescriptor,  # ex: Dashboard.team
                # related_descriptors.ReverseManyToOneDescriptor,  # ex: Dashboard.tiles
                related_descriptors.ForwardOneToOneDescriptor,
                related_descriptors.ManyToManyDescriptor,  # ex: Dashboard.insights
            ),
        )

    @classmethod
    def is_relation(cls, field_name: str) -> bool:
        backing_model = cls.get_model()
        field_definition = getattr(backing_model, field_name)

        if field_definition is None:
            return False

        # I think these are the only related object fields: https://docs.djangoproject.com/en/6.0/ref/models/relations/
        return isinstance(
            field_definition,
            (
                related_descriptors.ManyToManyDescriptor,
                related_descriptors.ReverseManyToOneDescriptor,
                related_descriptors.ForwardManyToOneDescriptor,
                related_descriptors.ForwardOneToOneDescriptor,
            ),
        )

    @classmethod
    def is_many_to_many_relation(cls, field_name: str) -> bool:
        return cls.is_relation(field_name) and isinstance(
            getattr(cls.get_model(), field_name), related_descriptors.ManyToManyDescriptor
        )

    @classmethod
    def is_primary_key(cls, field_name: str) -> bool:
        class_attr = getattr(cls.get_model(), field_name)

        if class_attr is None:
            return False

        return hasattr(class_attr, "field") and class_attr.field.primary_key

    @classmethod
    def is_immutable(cls) -> bool:
        """
        Return true if this is a visitor for a resource that should never be copied.
        """
        return cls.immutable
