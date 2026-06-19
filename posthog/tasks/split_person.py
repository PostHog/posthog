from typing import Optional

import structlog
from celery import shared_task

from posthog.models import Person
from posthog.scoping_audit import skip_team_scope_audit

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True, max_retries=1)
@skip_team_scope_audit
def split_person(
    person_id: int,
    team_id: int,
    main_distinct_id: Optional[str] = None,
    max_splits: Optional[int] = None,
    distinct_ids_to_split: Optional[list[str]] = None,
) -> None:
    """
    Split all distinct ids into separate persons

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

    try:
        # split_person() fetches the person via get_person_by_id internally,
        # so we only construct a stub here to avoid a redundant fetch.
        person = Person(pk=person_id, team_id=team_id)
        person.split_person(main_distinct_id, max_splits, distinct_ids_to_split=distinct_ids_to_split)

        logger.info(
            "split_person task completed",
            person_id=person_id,
            team_id=team_id,
        )
    except Exception as e:
        logger.exception(
            "split_person task failed",
            person_id=person_id,
            team_id=team_id,
            main_distinct_id=main_distinct_id,
            max_splits=max_splits,
            distinct_ids_to_split_count=len(distinct_ids_to_split) if distinct_ids_to_split is not None else None,
            error_type=type(e).__name__,
            error_message=str(e),
        )
        raise
