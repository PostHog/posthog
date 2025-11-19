from typing import Optional, Union

from celery import shared_task

from posthog.models import Person


@shared_task(ignore_result=True, max_retries=1)
def split_person(
    person_id: int,
    team_id: Union[int, str, None] = None,
    main_distinct_id: Optional[str] = None,
    max_splits: Optional[int] = None,
) -> None:
    """
    Split all distinct ids into separate persons

    Note: team_id is now required for efficient querying on partitioned tables.
    For backward compatibility during rolling deploys, if team_id looks like a string
    (old main_distinct_id position), we fall back to legacy behavior.
    """
    # Backward compatibility: detect old 3-arg signature (person_id, main_distinct_id, max_splits)
    # where second arg would be a string (distinct_id) or None
    if isinstance(team_id, str) or (team_id is None and main_distinct_id is None):
        # Old signature: split_person(person_id, main_distinct_id, max_splits)
        # Get team_id from PersonDistinctId to avoid scanning all partitions
        from posthog.models import PersonDistinctId

        old_main_distinct_id: Optional[str] = team_id if isinstance(team_id, str) else None
        old_max_splits: Optional[int] = main_distinct_id  # type: ignore[assignment]

        # Lookup team_id via PersonDistinctId which has person_id FK
        pdi = PersonDistinctId.objects.filter(person_id=person_id).only("team_id").first()
        if not pdi:
            raise ValueError(f"Cannot find team_id for person_id={person_id}")

        person = Person.objects.get(team_id=pdi.team_id, pk=person_id)
        person.split_person(old_main_distinct_id, old_max_splits)
    else:
        # New signature: split_person(person_id, team_id, main_distinct_id, max_splits)
        assert team_id is not None and isinstance(team_id, int), "team_id must be an int in new signature"
        person = Person.objects.get(team_id=team_id, pk=person_id)
        person.split_person(main_distinct_id, max_splits)
