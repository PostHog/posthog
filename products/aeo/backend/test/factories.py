import uuid

from posthog.models.scoping import team_scope
from posthog.models.team import Team

from products.aeo.backend.facade.contracts import BrandSource
from products.aeo.backend.models import AEOBrand, AEOCitationCheck, AEOPrompt


def create_citation_check(team: Team, label: str) -> uuid.UUID:
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
    return check.pk


def create_brand(team: Team, label: str) -> uuid.UUID:
    with team_scope(team.pk):
        brand = AEOBrand.objects.create(team=team, name=label, domain=f"{label}.example.com", source=BrandSource.MANUAL)
    return brand.pk
