from typing import Optional

from celery import shared_task

from posthog.models.person.person_api import PersonAPI


@shared_task(ignore_result=True, max_retries=1)
def split_person(team_id: int, person_id: int, main_distinct_id: Optional[str], max_splits: Optional[int]) -> None:
    """
    Split all distinct ids into separate persons
    """

    PersonAPI.split_person(team_id, person_id, main_distinct_id, max_splits)
