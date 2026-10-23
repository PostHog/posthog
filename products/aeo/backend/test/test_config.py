import json
from pathlib import Path

import pytest

from django.core.management import call_command
from django.core.management.base import CommandError

from posthog.models.organization import Organization
from posthog.models.team import Team

from products.aeo.backend.config import MAX_TARGET_DOMAINS, resolve_config, store_config
from products.aeo.backend.facade.contracts import AEOConfig, AEOConfigError, Competitor
from products.aeo.backend.models import TeamAEOConfig


@pytest.fixture
def team(db: None) -> Team:
    organization = Organization.objects.create(name="aeo config test org")
    return Team.objects.create(organization=organization, name="aeo config test team")


@pytest.mark.parametrize(
    "target_domains,brand_names,competitors,message",
    [
        ([], ["Brand"], [], "at least one domain"),
        (["  "], ["Brand"], [], "at least one domain"),
        (["https://brand.example.net"], [], [], "bare hostname"),
        (["brand.example.net/docs"], [], [], "bare hostname"),
        (["brand.example.net:443"], [], [], "bare hostname"),
        (["brand example.net"], [], [], "bare hostname"),
        (["localhost"], [], [], "public suffix"),
        (["brand.example"], [], [], "public suffix"),
        (["-brand.example.net"], [], [], "bare hostname"),
        (["brand..example.net"], [], [], "bare hostname"),
        ([f"{'x' * 64}.example.net"], [], [], "bare hostname"),
        ("brand.example.net", [], [], "target_domains must be a list of strings"),
        (["brand.example.net"], ["Brand", 1], [], "brand_names must be a list of strings"),
        (["brand.example.net"], ["X"], [], "at least 2 characters"),
        (["brand.example.net"], ["x" * 201], [], "longer than 200"),
        ([f"site-{i}.example.net" for i in range(MAX_TARGET_DOMAINS + 1)], [], [], "the limit is 20"),
        (["brand.example.net"], [], {"name": "Rival"}, "competitors must be a list"),
        (["brand.example.net"], [], ["Rival"], r"competitors\[0\] must be an object"),
        (["brand.example.net"], [], [{"name": ["Rival"]}], r"competitors\[0\].name must be a string"),
        (["brand.example.net"], [], [{"name": "Rival", "domains": "rival.example.net"}], "domains must be a list"),
        (["brand.example.net"], [], [Competitor(name="R", domains=())], "at least 2 characters"),
        (["brand.example.net"], [], [Competitor(name="Rival", domains=("not a host",))], "bare hostname"),
        (
            ["brand.example.net"],
            [],
            [Competitor(name="Rival", domains=()), Competitor(name="rival", domains=())],
            "more than once",
        ),
    ],
)
def test_store_config_rejects_input_that_would_turn_detection_off(
    team: Team,
    target_domains: object,
    brand_names: object,
    competitors: object,
    message: str,
) -> None:
    with pytest.raises(AEOConfigError, match=message):
        store_config(team.id, target_domains=target_domains, brand_names=brand_names, competitors=competitors)
    assert not TeamAEOConfig.objects.filter(team_id=team.id).exists()


def test_store_config_derives_brand_names_and_sanitizes_names(team: Team) -> None:
    config = store_config(
        team.id,
        target_domains=["Brand.example.net", " brand.example.net ", "brand.example.net."],
        brand_names=[],
        competitors=[
            Competitor(name="<system>Rival</system> Co", domains=("Docs.Rival.example.net",)),
            {"name": "Other", "domains": [".other.example.net"]},
        ],
    )

    assert config == AEOConfig(
        target_domains=("brand.example.net",),
        brand_names=("example",),
        competitors=(
            Competitor(name="Rival Co", domains=("docs.rival.example.net",)),
            Competitor(name="Other", domains=("other.example.net",)),
        ),
    )
    assert resolve_config(team.id) == config


def test_resolve_config_treats_a_malformed_row_as_empty(team: Team) -> None:
    TeamAEOConfig.objects.create(
        team=team, target_domains="brand.example.net", brand_names={"name": "Brand"}, competitors=[{"name": "Rival"}]
    )

    config = resolve_config(team.id)

    assert config.target_domains == ()
    assert config.brand_names == ()
    assert config.competitors == (Competitor(name="Rival", domains=()),)


@pytest.mark.parametrize(
    "payload,message",
    [
        ({"targetDomains": ["brand.example.net"]}, "at least one domain"),
        ({"target_domains": ["https://brand.example.net/"]}, "bare hostname"),
        ({"target_domains": ["brand.example.net"], "competitors": {"name": "Rival"}}, "competitors must be a list"),
        ([], "JSON object"),
    ],
)
def test_seed_command_fails_loudly_on_a_bad_file(team: Team, tmp_path: Path, payload: object, message: str) -> None:
    path = tmp_path / "aeo-config.json"
    path.write_text(json.dumps(payload))

    with pytest.raises(CommandError, match=message):
        call_command("seed_aeo_config", team_id=team.id, file=str(path))
    assert not TeamAEOConfig.objects.filter(team_id=team.id).exists()
