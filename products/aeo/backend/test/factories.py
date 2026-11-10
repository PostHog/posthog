import uuid
import datetime as dt

from posthog.models.scoping import team_scope
from posthog.models.team import Team

from products.aeo.backend.models import AEOCitationCheck, AEOPrompt


def create_citation_check(team: Team, label: str, *, created_at: dt.datetime | None = None) -> uuid.UUID:
    with team_scope(team.pk):
        prompt = AEOPrompt.objects.create(
            team=team, prompt=f"is {label} cited?", prompt_hash=label, prompt_source=AEOPrompt.Source.MANUAL
        )
        check = AEOCitationCheck.objects.create(
            team=team,
            prompt=prompt,
            run_id=uuid.uuid4(),
            prompt_text=prompt.prompt,
            prompt_source=prompt.prompt_source,
            prompt_hash=prompt.prompt_hash,
            engine="exa-answer",
            model="exa-answer",
        )
        if created_at is not None:
            # created_at is set on insert, so a check in the past is moved there afterwards.
            AEOCitationCheck.objects.filter(pk=check.pk).update(created_at=created_at)
    return check.pk
