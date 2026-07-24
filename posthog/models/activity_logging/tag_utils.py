from dataclasses import dataclass
from typing import Optional

from posthog.models.tagged_item import RELATED_OBJECTS


@dataclass(frozen=True)
class TaggedItemRelatedObject:
    """The related object's type, id, and name for a tagged item (all None when there is none).

    Not a tuple so a positional unpack can't silently reorder these same-typed strings.
    """

    type: Optional[str]
    id: Optional[str]
    name: Optional[str]


def get_tagged_item_related_object_info(tagged_item) -> TaggedItemRelatedObject:
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

    return TaggedItemRelatedObject(
        type=related_object_type,
        id=related_object_id,
        name=related_object_name,
    )
