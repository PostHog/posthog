from typing import Optional, Union

import structlog
from celery import shared_task

from posthog.models import Person

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True, max_retries=1)
def split_person(
    person_id: int,
    team_id: Union[int, str, None] = None,
    main_distinct_id: Optional[str] = None,
    max_splits: Optional[int] = None,
    distinct_ids_to_split: Optional[list[str]] = None,
) -> None:
    """
    Split all distinct ids into separate persons

    Note: team_id is now required for efficient querying on partitioned tables.
    For backward compatibility during rolling deploys, if team_id looks like a string
    (old main_distinct_id position), we fall back to legacy behavior.

    When ``distinct_ids_to_split`` is provided, only those specific distinct_ids are
    moved off of the original person; everything else (including properties) stays
    intact. See ``Person.split_person`` for details.
    """
    logger.info(
        "split_person task started",
        person_id=person_id,
        team_id=team_id,
        main_distinct_id=main_distinct_id,
        max_splits=max_splits,
        distinct_ids_to_split_count=len(distinct_ids_to_split) if distinct_ids_to_split is not None else None,
    )

    resolved_team_id: Union[int, None] = None

    try:
        # Backward compatibility: detect old 3-arg signature (person_id, main_distinct_id, max_splits)
        # where second arg would be a string (distinct_id) or None
        is_legacy = isinstance(team_id, str) or (team_id is None and main_distinct_id is None)
        logger.info(
            "split_person path determined",
            person_id=person_id,
            is_legacy=is_legacy,
            team_id_type=type(team_id).__name__,
        )
        if is_legacy:
            # Old signature: split_person(person_id, main_distinct_id, max_splits)
            # Get team_id from PersonDistinctId to avoid scanning all partitions
            from posthog.models import PersonDistinctId

            old_main_distinct_id: Optional[str] = team_id if isinstance(team_id, str) else None
            old_max_splits: Optional[int] = int(main_distinct_id) if main_distinct_id is not None else None

            logger.info(
                "split_person legacy path: querying PersonDistinctId for team_id",
                person_id=person_id,
            )
            # Lookup team_id via PersonDistinctId which has person_id FK
            pdi = PersonDistinctId.objects.filter(person_id=person_id).only("team_id").first()
            if not pdi:
                raise ValueError(f"Cannot find team_id for person_id={person_id}")

            resolved_team_id = pdi.team_id
            logger.info(
                "split_person legacy path: fetching Person",
                person_id=person_id,
                team_id=resolved_team_id,
            )
            person = Person.objects.get(team_id=resolved_team_id, pk=person_id)
            logger.info(
                "split_person legacy path: calling split_person on model",
                person_id=person_id,
                team_id=resolved_team_id,
                main_distinct_id=old_main_distinct_id,
                max_splits=old_max_splits,
            )
            person.split_person(old_main_distinct_id, old_max_splits, distinct_ids_to_split=distinct_ids_to_split)
        else:
            # New signature: split_person(person_id, team_id, main_distinct_id, max_splits)
            assert team_id is not None and isinstance(team_id, int), "team_id must be an int in new signature"
            resolved_team_id = team_id
            logger.info(
                "split_person new path: fetching Person",
                person_id=person_id,
                team_id=resolved_team_id,
            )
            person = Person.objects.get(team_id=resolved_team_id, pk=person_id)
            logger.info(
                "split_person new path: calling split_person on model",
                person_id=person_id,
                team_id=resolved_team_id,
                main_distinct_id=main_distinct_id,
                max_splits=max_splits,
            )
            person.split_person(main_distinct_id, max_splits, distinct_ids_to_split=distinct_ids_to_split)

        logger.info(
            "split_person task completed",
            person_id=person_id,
            team_id=resolved_team_id,
        )
    except Exception as e:
        logger.exception(
            "split_person task failed",
            person_id=person_id,
            team_id=resolved_team_id,
            main_distinct_id=main_distinct_id,
            max_splits=max_splits,
            distinct_ids_to_split_count=len(distinct_ids_to_split) if distinct_ids_to_split is not None else None,
            error_type=type(e).__name__,
            error_message=str(e),
        )
        raise
