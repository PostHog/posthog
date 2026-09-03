import uuid

from posthog.models.scoping import team_scope
from posthog.models.team import Team

from products.aeo.backend.models import AEOCitationCheck, AEOPrompt


def create_citation_check(team: Team, label: str) -> AEOCitationCheck:
    with team_scope(team.pk):
        prompt = AEOPrompt.objects.create(
            team=team, prompt=f"is {label} cited?", prompt_hash=label, prompt_source=AEOPrompt.Source.MANUAL
        )
        return AEOCitationCheck.objects.create(
            team=team,
            prompt=prompt,
            run_id=uuid.uuid4(),
            prompt_text=prompt.prompt,
            prompt_source=prompt.prompt_source,
            prompt_hash=prompt.prompt_hash,
            engine="exa-answer",
            model="exa-answer",
        )
