from django.core.exceptions import ValidationError
from django.db import models

from posthog.models.utils import UUIDTModel, build_partial_uniqueness_constraint, build_unique_relationship_check

RELATED_OBJECTS = ("group",)


class ResourceNotebook(UUIDTModel):
    """
    Generic relationship table linking notebooks to various resources.
    This allows notebooks to be associated with multiple models.

    Uses explicit foreign keys rather than GenericForeignKey for better performance
    and type safety.
    """

    notebook = models.ForeignKey("Notebook", on_delete=models.CASCADE, related_name="resources")

    # Relationships (exactly one must be set)
    # When adding a new foreign key, make sure to add the foreign key field and append field name
    # to the `RELATED_OBJECTS` tuple above.
    # Group relationship is not a foreign key because the table lives in another database instance, which would cause IntegrityErrors when inserting a new ResourceNotebook row.

    group = models.IntegerField(
        null=True,
        blank=True,
        db_column="group_id",
    )

    class Meta:
        unique_together = ("notebook", *RELATED_OBJECTS)
        constraints = [
            *[
                build_partial_uniqueness_constraint(
                    field="notebook",
                    related_field=related_field,
                    constraint_name=f"unique_notebook_{related_field}",
                )
                for related_field in RELATED_OBJECTS
            ],
            models.CheckConstraint(
                check=build_unique_relationship_check(RELATED_OBJECTS), name="exactly_one_notebook_related_resource"
            ),
        ]

    def clean(self):
        super().clean()
        """Ensure that exactly one resource field is set."""
        if sum(map(bool, [getattr(self, field) for field in RELATED_OBJECTS])) != 1:
            raise ValidationError("Exactly one resource field must be set.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    @property
    def resource_type(self) -> str:
        """Return the type of the related resource."""
        for field in RELATED_OBJECTS:
            if getattr(self, field):
                return field
        return "unknown"

    @property
    def resource(self):
        """Return the actual related resource object."""
        resource_type = self.resource_type
        if resource_type != "unknown":
            return getattr(self, resource_type)
        return None

    def __str__(self) -> str:
        return f"Notebook {self.notebook.short_id} -> {self.resource_type} {self.resource}"
