from uuid import uuid5, UUID

# JS code
# const PERSON_UUIDV5_NAMESPACE = parseUuid('932979b4-65c3-4424-8467-0b66ec27bc22')

# function uuidFromDistinctId(teamId: number, distinctId: string): string {
#     // Deterministcally create a UUIDv5 based on the (team_id, distinct_id) pair.
#     return uuidv5(`${teamId}:${distinctId}`, PERSON_UUIDV5_NAMESPACE)
# }


def uuidFromDistinctId(team_id: int, distinct_id: str) -> UUID:
    """
    Deterministically create a UUIDv5 based on the (team_id, distinct_id) pair.
    """
    return uuid5(UUID("932979b4-65c3-4424-8467-0b66ec27bc22"), f"{team_id}:{distinct_id}")


class MissingPerson:
    uuid: UUID
    properties: dict = {}

    def __init__(self, team_id: int, distinct_id: str):
        """
        This is loosely based on the plugin-server `person-state.ts` file and is meant to represent a person that is "missing"
        """
        self.team_id = team_id
        self.distinct_id = distinct_id
        self.uuid = uuidFromDistinctId(team_id, distinct_id)

    def __str__(self):
        return f"MissingPerson({self.team_id}, {self.distinct_id})"
