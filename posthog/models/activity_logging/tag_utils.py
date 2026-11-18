from posthog.dataclasses import frozen


@frozen
class RelatedObjectInfo:
    type: str | None
    id: str | None
    name: str | None


def get_tagged_item_related_object_info(tagged_item) -> RelatedObjectInfo:
    related_obj = tagged_item.content_object
    if related_obj is None:
        return RelatedObjectInfo(type=None, id=None, name=None)

    related_object_type = tagged_item.related_object_type

    if related_object_type == "insight" and hasattr(related_obj, "short_id"):
        related_object_id = str(related_obj.short_id)
    else:
        related_object_id = str(related_obj.id)

    related_object_name = None
    for attribute in ("name", "title", "label"):
        if hasattr(related_obj, attribute):
            related_object_name = getattr(related_obj, attribute)
            break

    return RelatedObjectInfo(type=related_object_type, id=related_object_id, name=related_object_name)
