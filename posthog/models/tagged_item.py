from django.core.exceptions import ValidationError
from django.db import models

from posthog.models.activity_logging.model_activity import ModelActivityMixin, get_current_user, get_was_impersonated
from posthog.models.utils import UUIDTModel, build_partial_uniqueness_constraint, build_unique_relationship_check

RELATED_OBJECTS = (
    "dashboard",
    "insight",
    "event_definition",
    "property_definition",
    "action",
    "feature_flag",
    "experiment_saved_metric",
)


class TaggedItem(ModelActivityMixin, UUIDTModel):
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

    tag = models.ForeignKey("Tag", on_delete=models.CASCADE, related_name="tagged_items")

    # When adding a new taggeditem-model relationship, make sure to add the foreign key field and append field name to
    # the `RELATED_OBJECTS` tuple above.
    dashboard = models.ForeignKey(
        "Dashboard",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="tagged_items",
    )
    insight = models.ForeignKey(
        "Insight",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="tagged_items",
    )
    event_definition = models.ForeignKey(
        "EventDefinition",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="tagged_items",
    )
    property_definition = models.ForeignKey(
        "PropertyDefinition",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="tagged_items",
    )
    action = models.ForeignKey(
        "Action",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="tagged_items",
    )
    feature_flag = models.ForeignKey(
        "FeatureFlag",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="tagged_items",
    )
    experiment_saved_metric = models.ForeignKey(
        "ExperimentSavedMetric",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="tagged_items",
    )

    class Meta:
        unique_together = ("tag", *RELATED_OBJECTS)
        # Make sure to add new key to uniqueness constraint when extending tag functionality to new model
        constraints = [
            *[
                build_partial_uniqueness_constraint(
                    field="tag", related_field=related_field, constraint_name=f"unique_{related_field}_tagged_item"
                )
                for related_field in RELATED_OBJECTS
            ],
            models.CheckConstraint(
                check=build_unique_relationship_check(RELATED_OBJECTS), name="exactly_one_related_object"
            ),
        ]

    def clean(self):
        super().clean()
        """Ensure that exactly one of object columns can be set."""
        if sum(map(bool, [getattr(self, o_field) for o_field in RELATED_OBJECTS])) != 1:
            raise ValidationError("Exactly one object field must be set.")

    def save(self, *args, **kwargs):
        self.full_clean()
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
