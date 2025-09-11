from typing import Optional

from posthog.models.tagged_item import RELATED_OBJECTS


def get_tagged_item_related_object_info(tagged_item) -> tuple[Optional[str], Optional[str], Optional[str]]:
    related_object_type = None
    related_object_id = None
    related_object_name = None

    for field_name in RELATED_OBJECTS:
        related_obj = getattr(tagged_item, field_name, None)
        if related_obj:
            related_object_type = field_name

            if field_name == "insight" and hasattr(related_obj, "short_id"):
                related_object_id = str(related_obj.short_id)
            else:
                related_object_id = str(related_obj.id)

            if hasattr(related_obj, "name"):
                related_object_name = related_obj.name
            elif hasattr(related_obj, "title"):
                related_object_name = related_obj.title
            elif hasattr(related_obj, "label"):
                related_object_name = related_obj.label
            break

    return related_object_type, related_object_id, related_object_name
