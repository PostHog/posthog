from typing import Any, List

from posthog.models.person import Person, PersonDistinctId


def delete_bulky_postgres_data(team_ids: List[int]):
    "Efficiently delete large tables for teams from postgres. Using normal CASCADE delete here can time out"

    _raw_delete(PersonDistinctId.objects.filter(team_id__in=team_ids))
    _raw_delete(Person.objects.filter(team_id__in=team_ids))


def _raw_delete(queryset: Any):
    "Issues a single DELETE statement for the queryset"
    queryset._raw_delete(queryset.db)
