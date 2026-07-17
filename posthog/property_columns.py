"""Type aliases naming the tables and columns that store event/person/group properties.

Django-free so the HogQL engine and the materialized-columns layer can import them without
booting Django; posthog.models.property re-exports them for existing callers.
"""

from typing import Literal

PropertyName = str
TableWithProperties = Literal["events", "person", "groups"]
TableColumn = Literal[
    "properties",  # for events & persons table
    "group_properties",  # for groups table
    # all below are for person&groups on events table
    "person_properties",
]
