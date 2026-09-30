"""The view-level description, stored as a column annotation with an empty column name."""

from rest_framework import serializers

from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.data_warehouse.backend.presentation.views.column_annotation_base import DESCRIPTION_HELP_TEXT

VIEW_DESCRIPTION_HELP_TEXT = (
    "Semantic description of what this view represents, surfaced to AI agents. Set it to describe the "
    "view; send an empty string to clear it. Per-column descriptions are read back in `columns` and set "
    "via the saved-query column annotation endpoints. " + DESCRIPTION_HELP_TEXT
)


def view_annotation_map(view: DataWarehouseSavedQuery) -> dict[str, str]:
    """`{column_name: description}` from a view's column annotations (``""`` = view-level)."""
    return {a.column_name: a.description for a in view.column_annotations.all()}


class ViewDescriptionField(serializers.CharField):
    """View-level description, stored as a column annotation with an empty `column_name`.

    Reads the annotation for display; on write the serializer's create/update upserts or clears it. The
    view model has no `description` column, so the value is resolved here rather than bound to the model.
    """

    def get_attribute(self, instance: DataWarehouseSavedQuery) -> str | None:
        return view_annotation_map(instance).get("")
