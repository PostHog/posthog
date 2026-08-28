"""Write a run down, together with the subjects it touched.

One entry point, because the two cannot be created apart. The history gates probe the stamp rows,
and a run missing its declared stamp is withheld from a restricted member rather than served. A
caller that could insert the run alone would strand its own history behind that gate.
"""

from typing import Any
from uuid import UUID

from django.db import transaction

from ..facade.enums import SubjectRelation
from ..models import DataQualityCheckRun, DataQualityCheckRunSubject
from .subject_access import pinned_subjects


def record_check_run(team_id: int, **fields: Any) -> DataQualityCheckRun:
    """Record one check execution, stamping the subjects it touched beside it."""
    with transaction.atomic():
        run = DataQualityCheckRun.objects.for_team(team_id).create(team_id=team_id, **fields)
        _stamp_subjects(run)
    return run


def _stamp_subjects(run: DataQualityCheckRun) -> None:
    rows = [
        DataQualityCheckRunSubject(
            team_id=run.team_id,
            run=run,
            relation=SubjectRelation.DECLARED,
            subject_type=run.subject_type,
            subject_uuid=run.subject_uuid,
            subject_name=run.subject_name,
        )
    ]
    # None (recorded before runs pinned this) and an empty list (read nothing beyond its subject)
    # both stamp no referenced row; the recorded column is what tells those two apart.
    # A query can name one object two ways (a dotted "stripe.charges" and the "stripe_charges" row it
    # resolves to), which pins the same id twice; dict.fromkeys keeps one, so the unique index does
    # not reject the repeat and roll the whole run back.
    for subject in dict.fromkeys(pinned_subjects(run.referenced_subjects) or []):
        rows.append(
            DataQualityCheckRunSubject(
                team_id=run.team_id,
                run=run,
                relation=SubjectRelation.REFERENCED,
                subject_type=subject.subject_type,
                subject_uuid=UUID(subject.subject_uuid),
            )
        )
    DataQualityCheckRunSubject.objects.for_team(run.team_id).bulk_create(rows)
