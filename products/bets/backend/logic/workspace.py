from django.db import IntegrityError, transaction

from posthog.models import Team
from posthog.models.scoping.manager import resolve_effective_team_id

from ..db import WRITER_DB
from ..models import BetsSettings


def project_id(team: Team) -> int:
    return resolve_effective_team_id(team.id)


def get_settings(team_id: int) -> BetsSettings:
    try:
        with transaction.atomic(using=WRITER_DB):
            result, _ = (
                BetsSettings.objects.for_team(team_id, canonical=True).using(WRITER_DB).get_or_create(team_id=team_id)
            )
            return result
    except IntegrityError:
        return BetsSettings.objects.for_team(team_id, canonical=True).using(WRITER_DB).get()
