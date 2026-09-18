"""The `Taggable` base every taggable model inherits, and the relation it adds.

It is a Django `GenericRelation` that stores and reads every tag under the content type
of the registered base model. Plain `GenericRelation` reads the content type off the
instance class in its manager, and off a per-subclass copy of the field in its joins. An
enterprise event definition would then write and look for its tags under its own content
type, and miss every tag written through the base model.

The relation reads through `tag_read_pointer`, so the flag in `tagged_item_reads` picks
the columns for its manager, its prefetches, and its joins.
"""

from typing import Any, cast

from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation, ReverseGenericManyToOneDescriptor
from django.contrib.contenttypes.models import ContentType
from django.db import DEFAULT_DB_ALIAS, models
from django.db.models.sql.where import WhereNode
from django.utils.functional import cached_property

from posthog.models.tagged_item_reads import tag_read_pointer
from posthog.models.tagged_item_registry import content_type_for, require_taggable


class _TaggedItemsDescriptor(ReverseGenericManyToOneDescriptor):
    @cached_property
    def related_manager_cls(self) -> type:
        generic_manager_cls: Any = super().related_manager_cls

        class TaggedItemsManager(generic_manager_cls):
            def __init__(self, instance: models.Model | None = None) -> None:
                super().__init__(instance)
                self.get_content_type = lambda obj, **_: content_type_for(type(obj))
                self.content_type = self.get_content_type(instance)
                pointer = tag_read_pointer(type(cast(models.Model, instance)))
                self.object_id_field_name = pointer.object_column
                self.content_type_id_filter = pointer.content_type_id
                self.core_filters = {pointer.object_column: self.pk_val}
                if pointer.content_type_id is not None:
                    self.core_filters[f"{self.content_type_field_name}__pk"] = pointer.content_type_id

            def get_prefetch_querysets(
                self, instances: list[models.Model], querysets: list[models.QuerySet] | None = None
            ) -> tuple[Any, ...]:
                if self.content_type_id_filter is not None:
                    return super().get_prefetch_querysets(instances, querysets)
                # The legacy pointer has no content type to group on, so match on the key alone.
                column = self.object_id_field_name
                queryset: Any = querysets[0] if querysets else super(generic_manager_cls, self).get_queryset()
                queryset._add_hints(instance=instances[0])
                queryset = queryset.using(queryset._db or self._db)
                to_key = instances[0]._meta.pk.to_python
                return (
                    # nosemgrep: orm-field-injection -- the name comes from the closed TAGGABLE_MODELS registry, never from input
                    queryset.filter(**{f"{column}__in": {obj.pk for obj in instances}}),
                    lambda relobj: to_key(getattr(relobj, column)),
                    lambda obj: obj.pk,
                    False,
                    self.prefetch_cache_name,
                    False,
                )

        return TaggedItemsManager


class TaggedItemsRelation(GenericRelation):
    """The field behind `Taggable.tagged_items`."""

    generic_object_field = "object_id"

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("to", "posthog.TaggedItem")
        super().__init__(**kwargs)

    @property
    def object_id_field_name(self) -> str:
        model = getattr(self, "model", None)
        if model is None or model._meta.abstract:
            return self.generic_object_field
        return tag_read_pointer(model).object_column

    @object_id_field_name.setter
    def object_id_field_name(self, value: str) -> None:
        self.generic_object_field = value

    # Django caches these on the field. They depend on the flag, so compute them on each use.
    @property
    def related_fields(self) -> list[tuple[models.Field, models.Field]]:
        return self.resolve_related_fields()

    @property
    def reverse_related_fields(self) -> list[tuple[models.Field, models.Field]]:
        return [(rhs, lhs) for lhs, rhs in self.related_fields]

    @property
    def local_related_fields(self) -> tuple[models.Field, ...]:
        return tuple(lhs for lhs, _ in self.related_fields)

    @property
    def foreign_related_fields(self) -> tuple[models.Field, ...]:
        return tuple(rhs for _, rhs in self.related_fields if rhs)

    def contribute_to_class(self, cls: type[models.Model], name: str, **kwargs: Any) -> None:  # type: ignore[override]
        # The abstract Taggable base is not in the registry; each concrete subclass gets its own copy.
        if not cls._meta.abstract:
            self.generic_object_field = require_taggable(cls).object_field
        super().contribute_to_class(cls, name, **kwargs)
        setattr(cls, self.name, _TaggedItemsDescriptor(cast(Any, self.remote_field)))

    def _is_matching_generic_foreign_key(self, field: Any) -> bool:
        return (
            isinstance(field, GenericForeignKey)
            and field.ct_field == self.content_type_field_name
            and field.fk_field == self.generic_object_field
        )

    def get_content_type(self) -> ContentType:
        return content_type_for(self.model)

    # The stubs still carry Django's removed `where_class` argument, so pass the arguments through.
    def get_extra_restriction(self, *args: Any) -> WhereNode | None:  # type: ignore[override]
        if tag_read_pointer(self.model).content_type_id is None:
            return None
        return cast(Any, super()).get_extra_restriction(*args)

    def bulk_related_objects(self, objs: list[models.Model], using: str = DEFAULT_DB_ALIAS) -> models.QuerySet:
        pointer = tag_read_pointer(self.model)
        return self.remote_field.model._base_manager.db_manager(using).filter(
            pointer.matching([obj.pk for obj in objs], "in")
        )


class Taggable(models.Model):
    """Makes a model taggable. The model must also be listed in TAGGABLE_MODELS."""

    tagged_items = TaggedItemsRelation()

    class Meta:
        abstract = True
