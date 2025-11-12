from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from uuid import UUID


@dataclass()
class PersonDTO:
    id: int
    uuid: UUID
    team_id: int
    distinct_ids: list[str]
    properties: dict
    created_at: datetime
    updated_at: datetime


class PersonNotFoundException(Exception):
    pass


class PersonAPI:
    @staticmethod
    def get_person(cls, team_id: int, person_id: int) -> PersonDTO:
        raise NotImplementedError("Not implemented")

    @staticmethod
    def get_person_by_distinct_id(cls, team_id: int, distinct_id: str) -> PersonDTO:
        raise NotImplementedError("Not implemented")

    @staticmethod
    def split_person(
        cls, team_id: int, person_id: int, main_distinct_id: Optional[str], max_splits: Optional[int]
    ) -> None:
        raise NotImplementedError("Not implemented")
