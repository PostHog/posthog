"""Keep the restricted property names stored in a custom events schema away from other users.

This module must stay import-light, because the activity-log receiver loads in every process, workers included.
"""

import typing


def remove_saved_restrictions(schema: dict[str, typing.Any] | None) -> dict[str, typing.Any] | None:
    """Return the schema without the property names that the user who last saved it cannot read.

    A schema stores those names twice: in `restricted_properties`, so a native run can recompile its query with the
    same restrictions, and in the `_sensitive` query values that list the keys a field drops from a properties object.
    Anyone who can read the export or the activity log would otherwise see that user's restrictions. Runs read the full
    schema, because they need both.
    """
    if schema is None:
        return None
    redacted = {key: value for key, value in schema.items() if key != "restricted_properties"}
    if isinstance(redacted.get("values"), dict):
        redacted["values"] = {key: value for key, value in redacted["values"].items() if not key.endswith("_sensitive")}
    return redacted
