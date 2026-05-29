from typing import Literal

from posthog.personhog_client.proto import CONSISTENCY_LEVEL_EVENTUAL, CONSISTENCY_LEVEL_STRONG, ReadOptions

ReadConsistency = Literal["strong", "eventual"]

PERSON_FIELDS_WITHOUT_PROPERTIES: list[str] = [
    "id",
    "uuid",
    "team_id",
    "created_at",
    "version",
    "is_identified",
    "is_user_id",
    "last_seen_at",
]

READ_OPTIONS_WITHOUT_PROPERTIES = ReadOptions(field_mask=PERSON_FIELDS_WITHOUT_PROPERTIES)


def consistency_to_read_options(consistency: ReadConsistency) -> ReadOptions:
    level = CONSISTENCY_LEVEL_STRONG if consistency == "strong" else CONSISTENCY_LEVEL_EVENTUAL
    return ReadOptions(consistency=level)
