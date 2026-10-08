from collections.abc import Iterable
from typing import Any

from django.contrib.contenttypes.fields import GenericForeignKey
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, OuterRef, Q
from django.db.models.functions import Cast

from posthog.models.activity_logging.model_activity import ModelActivityMixin, get_current_user, get_was_impersonated
from posthog.models.tag import Tag
from posthog.models.tagged_item_registry import (
    TaggableModel,
    content_type_for,
    content_type_for_entry,
    object_column_for,
    require_taggable,
    taggable_for_content_type_id,
)
from posthog.models.utils import UUIDTModel

GENERIC_POINTER_FIELDS = ("content_type", "object_id", "object_uuid", "team")


class TaggedItemQuerySet(models.QuerySet):
    """Ways of selecting tagged items by what they tag, without naming a column."""

    def for_model(self, model: type[models.Model]) -> "TaggedItemQuerySet":
        """Rows tagging any instance of this model."""
        return self.filter(content_type=content_type_for(model))

    def for_object(self, obj: models.Model) -> "TaggedItemQuerySet":
        """Rows tagging this exact instance."""
        return self.for_objects(type(obj), [obj.pk])

    def for_objects(self, model: type[models.Model], pks: Iterable[Any]) -> "TaggedItemQuerySet":
        """Rows tagging any of these instances of one model."""
        # nosemgrep: orm-field-injection -- the name comes from the closed TAGGABLE_MODELS registry, never from input
        return self.for_model(model).filter(**{f"{object_column_for(model)}__in": pks})

    def matching_outer(self, model: type[models.Model], outer_field: str = "pk") -> "TaggedItemQuerySet":
        """Rows whose tagged object is the outer query's row, for use inside Exists or Subquery."""
        # nosemgrep: orm-field-injection -- the name comes from the closed TAGGABLE_MODELS registry, never from input
        return self.for_model(model).filter(**{object_column_for(model): OuterRef(outer_field)})

    def bulk_create(self, objs: Iterable["TaggedItem"], *args: Any, **kwargs: Any) -> list["TaggedItem"]:
        """Fill the generic pointer on each row, because bulk_create never calls save()."""
        objs = list(objs)
        uncached_tag_ids = {obj.tag_id for obj in objs if not TaggedItem.tag.is_cached(obj)}
        tags = Tag.objects.in_bulk(uncached_tag_ids) if uncached_tag_ids else {}
        for obj in objs:
            if obj.tag_id in tags:
                obj.tag = tags[obj.tag_id]
            obj.sync_team()
        return super().bulk_create(objs, *args, **kwargs)


class TaggedItem(ModelActivityMixin, UUIDTModel):
    """
    Taggable describes global tag-object relationships.
    Note: This is an EE only feature, however the model exists in posthog so that it is backwards accessible from all
    models. Whether we should be able to interact with this table is determined in the `TaggedItemSerializer` which
    imports `EnterpriseTaggedItemSerializer` if the feature is available.

    Today, tags exist at the model-level making it impossible to aggregate, filter, and query objects appwide by tags.
    We want to deprecate model-specific tags and refactor tag relationships into a separate table that keeps track of
    tag-object relationships.

    Models that are taggable throughout the app are listed in `TAGGABLE_MODELS`.
    https://docs.djangoproject.com/en/4.0/ref/contrib/contenttypes/#generic-relations
    """

    tag = models.ForeignKey("Tag", on_delete=models.CASCADE, related_name="tagged_items")

    # db_index=False on both keys below: Django would build that index non-concurrently
    # inside the AddField transaction, locking the table.
    content_type = models.ForeignKey(
        "contenttypes.ContentType",
        # A model moving between apps deletes the stale ContentType row, and CASCADE there
        # would take every tag on that model with it.
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        db_index=False,
    )
    object_id = models.IntegerField(null=True, blank=True)
    object_uuid = models.UUIDField(null=True, blank=True)
    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="+",
        # posthog_team is read on nearly every request, so an inline constraint would lock it.
        db_constraint=False,
        db_index=False,
    )
    integer_object = GenericForeignKey("content_type", "object_id")
    uuid_object = GenericForeignKey("content_type", "object_uuid")

    class Meta:
        indexes = [
            # Most integer-keyed models declare BigAutoField, so Django casts object_id to bigint
            # when it joins to them, and the unique index on the raw column cannot serve that join.
            models.Index(
                F("content_type"),
                Cast("object_id", output_field=models.BigIntegerField()),
                condition=Q(object_id__isnull=False),
                name="taggeditem_object_id_bigint",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(content_type__isnull=False, team__isnull=False)
                & (
                    Q(object_id__isnull=False, object_uuid__isnull=True)
                    | Q(object_id__isnull=True, object_uuid__isnull=False)
                ),
                name="taggeditem_generic_pointer_set",
            ),
            models.UniqueConstraint(
                fields=["content_type", "object_id", "tag"],
                condition=Q(object_id__isnull=False),
                name="unique_taggeditem_object_id",
            ),
            models.UniqueConstraint(
                fields=["content_type", "object_uuid", "tag"],
                condition=Q(object_uuid__isnull=False),
                name="unique_taggeditem_object_uuid",
            ),
        ]

    def clean(self):
        """Ensure the row names exactly one taggable object, through the column its model uses."""
        super().clean()
        if self.content_type_id is None:
            raise ValidationError("A tagged item must have a content type.")
        if (self.object_id is None) == (self.object_uuid is None):
            raise ValidationError("Exactly one object column must be set.")
        entry = self._taggable_entry
        if entry is None:
            raise ValidationError("The content type is not a taggable model.")
        if getattr(self, entry.object_field) is None:
            raise ValidationError(f"A tag on {self.content_type} belongs on {entry.object_field}.")

    objects = TaggedItemQuerySet.as_manager()

    @classmethod
    def for_content_object(cls, tag: Tag, content_object: models.Model) -> "TaggedItem":
        """An unsaved row tagging `content_object`, for callers that build rows in bulk."""
        entry = require_taggable(type(content_object))
        item = cls(tag=tag, content_type=content_type_for_entry(entry))
        setattr(item, entry.object_field, content_object.pk)
        return item

    @property
    def _taggable_entry(self) -> TaggableModel | None:
        return taggable_for_content_type_id(self.content_type_id) if self.content_type_id is not None else None

    @property
    def related_object_type(self) -> str | None:
        """Which kind of object this row tags, as the string activity-log rows already hold.

        Activity-log rows persist this value and the frontend describer switches on it, so it
        stays the old foreign key name rather than becoming a content-type model name.
        """
        entry = self._taggable_entry
        return entry.legacy_field if entry is not None else None

    @property
    def content_object(self) -> models.Model | None:
        """The object this row tags."""
        if self.object_id is not None:
            return self.integer_object
        if self.object_uuid is not None:
            return self.uuid_object
        return None

    def sync_team(self) -> None:
        """Take the team from the tag, which is the row's owner."""
        self.team_id = self.tag.team_id

    def save(self, *args, **kwargs):
        self.sync_team()
        self.full_clean()
        if kwargs.get("update_fields"):
            kwargs["update_fields"] = {*kwargs["update_fields"], *GENERIC_POINTER_FIELDS}
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return str(self.tag)

    def delete(self, *args, **kwargs):
        from posthog.models.signals import model_activity_signal

        model_activity_signal.send(
            sender=self.__class__,
            scope=self.__class__.__name__,
            before_update=self,
            after_update=None,
            activity="deleted",
            user=get_current_user(),
            was_impersonated=get_was_impersonated(),
        )

        return super().delete(*args, **kwargs)
