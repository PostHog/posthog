from typing import List, Union

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q, UniqueConstraint

from posthog.models.utils import UUIDModel

RELATED_OBJECTS = ("dashboard", "insight", "event_definition", "property_definition", "action")


# Checks that exactly one object field is populated
def build_check():
    built_check_list: List[Union[Q, Q]] = []
    for field in RELATED_OBJECTS:
        built_check_list.append(
            Q(*[(f"{other_field}__isnull", other_field != field) for other_field in RELATED_OBJECTS], _connector="AND")
        )
    return Q(*built_check_list, _connector="OR")


# Enforces uniqueness on tag_{object_field}. All permutations of null columns must be explicit as Postgres ignores
# uniqueness across null columns.
def build_partial_uniqueness_constraint(field: str):
    return UniqueConstraint(
        fields=["tag", field], name=f"unique_{field}_tagged_item", condition=Q((f"{field}__isnull", False)),
    )


class TaggedItem(UUIDModel):
    """
    Taggable describes global tag-object relationships.
    Note: This is an EE only feature, however the model exists in posthog so that it is backwards accessible from all
    models. Whether we should be able to interact with this table is determined in the `TaggedItemSerializer` which
    imports `EnterpriseTaggedItemSerializer` if the feature is available.

    Today, tags exist at the model-level making it impossible to aggregate, filter, and query objects appwide by tags.
    We want to deprecate model-specific tags and refactor tag relationships into a separate table that keeps track of
    tag-object relationships.

    Models that are taggable throughout the app are listed as separate fields below.
    https://docs.djangoproject.com/en/4.0/ref/contrib/contenttypes/#generic-relations
    """

    tag: models.ForeignKey = models.ForeignKey("Tag", on_delete=models.CASCADE, related_name="tagged_items")

    # When adding a new taggeditem-model relationship, make sure to add the foreign key field and append field name to
    # the `RELATED_OBJECTS` tuple above.
    dashboard: models.ForeignKey = models.ForeignKey(
        "Dashboard", on_delete=models.CASCADE, null=True, blank=True, related_name="tagged_items"
    )
    insight: models.ForeignKey = models.ForeignKey(
        "Insight", on_delete=models.CASCADE, null=True, blank=True, related_name="tagged_items"
    )
    event_definition: models.ForeignKey = models.ForeignKey(
        "EventDefinition", on_delete=models.CASCADE, null=True, blank=True, related_name="tagged_items"
    )
    property_definition: models.ForeignKey = models.ForeignKey(
        "PropertyDefinition", on_delete=models.CASCADE, null=True, blank=True, related_name="tagged_items"
    )
    action: models.ForeignKey = models.ForeignKey(
        "Action", on_delete=models.CASCADE, null=True, blank=True, related_name="tagged_items"
    )

    class Meta:
        unique_together = ("tag",) + RELATED_OBJECTS
        # Make sure to add new key to uniqueness constraint when extending tag functionality to new model
        constraints = [
            *[build_partial_uniqueness_constraint(field=field) for field in RELATED_OBJECTS],
            models.CheckConstraint(check=build_check(), name="exactly_one_related_object",),
        ]

    def clean(self):
        super().clean()
        """Ensure that exactly one of object columns can be set."""
        if sum(map(bool, [getattr(self, o_field) for o_field in RELATED_OBJECTS])) != 1:
            raise ValidationError("Exactly one object field must be set.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super(TaggedItem, self).save(*args, **kwargs)

    def __str__(self) -> str:
        return str(self.tag)
