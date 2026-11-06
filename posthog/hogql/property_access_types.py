from posthog.dataclasses import frozen


@frozen
class RestrictedProperty:
    name: str
    property_type: int
    group_type_index: int | None = None
