"""The `Taggable` base every taggable model inherits, and the relation it adds.

It is a Django `GenericRelation` that stores and reads every tag under the content type
of the registered base model. Plain `GenericRelation` reads the content type off the
instance class in its manager, and off a per-subclass copy of the field in its joins. An
enterprise event definition would then write and look for its tags under its own content
type, and miss every tag written through the base model.
"""

from typing import Any, cast

from django.contrib.contenttypes.fields import GenericRelation, ReverseGenericManyToOneDescriptor
from django.contrib.contenttypes.models import ContentType
from django.db import DEFAULT_DB_ALIAS, models
from django.utils.functional import cached_property

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
                self.core_filters[f"{self.content_type_field_name}__pk"] = self.content_type.id

            # Both would move rows between objects with an UPDATE that skips TaggedItem.save() and
            # leaves the legacy key stale. set() is refused before it opens its transaction.
            def add(self, *objs: models.Model, bulk: bool = True) -> None:
                raise NotImplementedError("Tagged items cannot move between objects. Create a new row instead.")

            def set(self, objs: Any, *, bulk: bool = True, clear: bool = False) -> None:
                raise NotImplementedError("Tagged items cannot move between objects. Create a new row instead.")

        return TaggedItemsManager


class TaggedItemsRelation(GenericRelation):
    """The field behind `Taggable.tagged_items`."""

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("to", "posthog.TaggedItem")
        super().__init__(**kwargs)

    def contribute_to_class(self, cls: type[models.Model], name: str, **kwargs: Any) -> None:  # type: ignore[override]
        # The abstract Taggable base is not in the registry; each concrete subclass gets its own copy.
        if not cls._meta.abstract:
            self.object_id_field_name = require_taggable(cls).object_field
        super().contribute_to_class(cls, name, **kwargs)
        setattr(cls, self.name, _TaggedItemsDescriptor(cast(Any, self.remote_field)))

    def get_content_type(self) -> ContentType:
        return content_type_for(self.model)

    def bulk_related_objects(self, objs: list[models.Model], using: str = DEFAULT_DB_ALIAS) -> models.QuerySet:
        return self.remote_field.model._base_manager.db_manager(using).filter(
            **{
                f"{self.content_type_field_name}__pk": self.get_content_type().pk,
                f"{self.object_id_field_name}__in": [obj.pk for obj in objs],
            }
        )


class Taggable(models.Model):
    """Makes a model taggable. The model must also be listed in TAGGABLE_MODELS."""

    tagged_items = TaggedItemsRelation()

    class Meta:
        abstract = True
