from typing import Literal

from posthog.personhog_client.proto import CONSISTENCY_LEVEL_EVENTUAL, CONSISTENCY_LEVEL_STRONG, Person, ReadOptions

ReadConsistency = Literal["strong", "eventual"]

_PERSON_PROPERTIES_FIELDS = frozenset({"properties", "properties_last_updated_at", "properties_last_operation"})

PERSON_FIELDS_WITHOUT_PROPERTIES: list[str] = [
    f.name for f in Person.DESCRIPTOR.fields if f.name not in _PERSON_PROPERTIES_FIELDS
]

READ_OPTIONS_WITHOUT_PROPERTIES = ReadOptions(field_mask=PERSON_FIELDS_WITHOUT_PROPERTIES)


def consistency_to_read_options(consistency: ReadConsistency) -> ReadOptions:
    level = CONSISTENCY_LEVEL_STRONG if consistency == "strong" else CONSISTENCY_LEVEL_EVENTUAL
    return ReadOptions(consistency=level)
