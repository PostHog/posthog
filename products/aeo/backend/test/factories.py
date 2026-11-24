import uuid

from posthog.models.scoping import team_scope
from posthog.models.team import Team

from products.aeo.backend.brand import names_brand
from products.aeo.backend.catalog import own_domains
from products.aeo.backend.check_brands import BrandMatcher, catalog_identities, write_check_brands
from products.aeo.backend.facade.contracts import BrandKind, BrandSource, BrandStatus
from products.aeo.backend.facts import write_facts
from products.aeo.backend.models import AEOBrand, AEOCitationCheck, AEOPrompt
from products.aeo.backend.stored_results import bump_data_version_on_commit


def create_own_brand(team: Team, domain: str) -> None:
    AEOBrand.objects.for_team(team.pk).create(
        team=team,
        name=domain,
        domain=domain,
        kind=BrandKind.OWN,
        status=BrandStatus.CONFIRMED,
        source=BrandSource.MANUAL,
    )


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


def store_what_the_runner_stores(check_id: uuid.UUID) -> None:
    """Give a check a test created directly the values the runner stores with it. Call it once the
    check has its final `created_at`, which the fact rows copy."""
    check = AEOCitationCheck.objects.unscoped().get(id=check_id)
    check.prompt_branded = names_brand(check.prompt_text, own_domains(check.team_id))
    check.save(update_fields=["prompt_branded"])
    write_facts([check])
    write_check_brands([check], BrandMatcher(catalog_identities(check.team_id)))
    bump_data_version_on_commit(check.team_id)
