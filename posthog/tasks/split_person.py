from celery import shared_task

from posthog.models import Person


@shared_task(ignore_result=True, max_retries=1)
def split_person(person_id: int, main_distinct_id: str | None, max_splits: int | None) -> None:
    """
    Split all distinct ids into separate persons
    """
    person = Person.objects.get(pk=person_id)
    person.split_person(main_distinct_id, max_splits)
