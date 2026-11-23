# Generator inputs shaped like the database models, with the descriptions a database row has, for the
# test that holds the generators' output for database callers unchanged.
from types import SimpleNamespace


def database_inputs() -> tuple[list[SimpleNamespace], dict[str, list[SimpleNamespace]]]:
    def prop(name: str, property_type: str, is_required: bool, is_optional_in_types: bool = False) -> SimpleNamespace:
        return SimpleNamespace(
            name=name,
            property_type=property_type,
            is_required=is_required,
            is_optional_in_types=is_optional_in_types,
            description=f"The {name} the customer chose",
        )

    events = [
        SimpleNamespace(id="1", name="$pageview", description="A page was viewed"),
        SimpleNamespace(id="2", name="file downloaded", description="A file was downloaded"),
        SimpleNamespace(id="3", name="user'event\"with\\quotes", description=""),
    ]
    schema_map = {
        "2": [
            prop("file_name", "String", True),
            prop("file_size", "Numeric", True),
            prop("downloaded_at", "DateTime", True),
            prop("file_extension", "String", False),
            prop("tags", "Array", False),
            prop("metadata", "Object", False),
            prop("is_public", "Boolean", False),
            prop("checksum", "String", True, is_optional_in_types=True),
        ],
        "3": [prop("prop'with\"quotes", "String", True)],
    }
    return events, schema_map
