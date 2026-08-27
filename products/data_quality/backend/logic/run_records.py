"""Write a run down, together with the subjects it read.

One entry point, because the two cannot be created apart. The history gates query the index rows,
and a run missing them reads as one that referenced nothing -- which is the fail-open answer. A
caller that could insert the run alone would be able to produce that state.
"""

from typing import Any
from uuid import UUID

from django.db import transaction

from ..models import DataQualityCheckRun, DataQualityCheckRunSubject
from .subject_access import pinned_subjects


def record_check_run(team_id: int, **fields: Any) -> DataQualityCheckRun:
    """Record one check execution, indexing whatever ``referenced_subjects`` says it read."""
    with transaction.atomic():
        run = DataQualityCheckRun.objects.for_team(team_id).create(team_id=team_id, **fields)
        _index_referenced_subjects(run)
    return run


def _index_referenced_subjects(run: DataQualityCheckRun) -> None:
    # None (recorded before runs pinned this) and an empty list (read nothing beyond its subject)
    # both index nothing; the recorded column is what tells those two apart.
    pinned = pinned_subjects(run.referenced_subjects)
    if not pinned:
        return
    # One row per identity. A query can name one object two ways (a dotted "stripe.charges" and the
    # "stripe_charges" row it resolves to), which pins the same id twice. Without this the unique
    # index rejects the repeat and rolls the whole run back. dict.fromkeys keeps first-seen order.
    DataQualityCheckRunSubject.objects.for_team(run.team_id).bulk_create(
        DataQualityCheckRunSubject(
            team_id=run.team_id,
            run=run,
            subject_type=subject.subject_type,
            subject_uuid=UUID(subject.subject_uuid),
        )
        for subject in dict.fromkeys(pinned)
    )
