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


def _config(
    target_domains: tuple[str, ...] = ("brand.example.net",),
    brand_names: tuple[str, ...] = (),
    competitors: tuple[Competitor, ...] = (),
) -> AEOConfig:
    return AEOConfig(target_domains=target_domains, brand_names=brand_names, competitors=competitors)


@pytest.mark.parametrize(
    "config,message",
    [
        (_config(target_domains=()), "at least one domain"),
        (_config(target_domains=("  ",)), "at least one domain"),
        (_config(target_domains=("https://brand.example.net",)), "bare hostname"),
        (_config(target_domains=("brand.example.net/docs",)), "bare hostname"),
        (_config(target_domains=("brand.example.net:443",)), "bare hostname"),
        (_config(target_domains=("brand example.net",)), "bare hostname"),
        (_config(target_domains=("localhost",)), "bare hostname"),
        (_config(target_domains=("brand.example",)), "bare hostname"),
        (_config(target_domains=("-brand.example.net",)), "bare hostname"),
        (_config(target_domains=("brand..example.net",)), "bare hostname"),
        (_config(target_domains=(f"{'x' * 64}.example.net",)), "bare hostname"),
        (_config(target_domains=tuple(f"site-{i}.example.net" for i in range(MAX_TARGET_DOMAINS + 1))), "limit is 20"),
        (_config(brand_names=("X",)), "at least 2 characters"),
        (_config(brand_names=("x" * 201,)), "longer than 200"),
        (_config(competitors=(Competitor(name="R", domains=()),)), "at least 2 characters"),
        (_config(competitors=(Competitor(name="Rival", domains=("not a host",)),)), "bare hostname"),
        (
            _config(competitors=(Competitor(name="Rival", domains=()), Competitor(name="rival", domains=()))),
            "more than once",
        ),
    ],
)
def test_store_config_rejects_input_that_would_turn_detection_off(team: Team, config: AEOConfig, message: str) -> None:
    with pytest.raises(AEOConfigError, match=message):
        store_config(team.id, config)
    assert not TeamAEOConfig.objects.filter(team_id=team.id).exists()


def test_store_config_derives_brand_names_and_sanitizes_names(team: Team) -> None:
    config = store_config(
        team.id,
        _config(
            target_domains=("Brand.example.net", " brand.example.net ", "brand.example.net."),
            competitors=(
                Competitor(name="<system>Rival</system> Co", domains=("Docs.Rival.example.net",)),
                Competitor(name="Other", domains=(".other.example.net",)),
            ),
        ),
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
        team=team,
        target_domains="brand.example.net",
        brand_names={"name": "Brand"},
        competitors=[{"name": "Rival"}, {"name": 5, "domains": []}],
    )

    config = resolve_config(team.id)

    assert config.target_domains == ()
    assert config.brand_names == ()
    assert config.competitors == (Competitor(name="Rival", domains=()),)


def _seed(team_id: int, path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload))
    call_command("seed_aeo_config", team_id=team_id, file=str(path))


def test_seed_command_stores_the_file(team: Team, tmp_path: Path) -> None:
    _seed(
        team.id,
        tmp_path / "aeo-config.json",
        {
            "target_domains": ["brand.example.net"],
            "brand_names": ["Brand Co"],
            "competitors": [{"name": "Rival", "domains": ["rival.example.net"]}, {"name": "Other"}],
        },
    )

    assert resolve_config(team.id) == AEOConfig(
        target_domains=("brand.example.net",),
        brand_names=("Brand Co",),
        competitors=(Competitor(name="Rival", domains=("rival.example.net",)), Competitor(name="Other", domains=())),
    )


@pytest.mark.parametrize(
    "payload,message",
    [
        ({"targetDomains": ["brand.example.net"]}, r"Unknown key\(s\) \['targetDomains'\]"),
        ({"target_domains": []}, "at least one domain"),
        ({"target_domains": "brand.example.net"}, "target_domains must be a list of strings"),
        ({"target_domains": ["https://brand.example.net/"]}, "bare hostname"),
        ({"target_domains": ["brand.example.net"], "brand_names": ["Brand", 1]}, "brand_names must be a list"),
        ({"target_domains": ["brand.example.net"], "competitors": {"name": "Rival"}}, "competitors must be a list"),
        ({"target_domains": ["brand.example.net"], "competitors": ["Rival"]}, r"competitors\[0\] must be an object"),
        ({"target_domains": ["brand.example.net"], "competitors": [{"name": ["Rival"]}]}, r"competitors\[0\] must be"),
        (
            {
                "target_domains": ["brand.example.net"],
                "competitors": [{"name": "Rival", "domains": "rival.example.net"}],
            },
            r"competitors\[0\].domains must be a list",
        ),
        (
            {
                "target_domains": ["brand.example.net"],
                "competitors": [{"name": "Rival", "domians": ["rival.example.net"]}],
            },
            r"competitors\[0\] has unknown key\(s\) \['domians'\]",
        ),
        ([], "JSON object"),
    ],
)
def test_seed_command_fails_loudly_on_a_bad_file(team: Team, tmp_path: Path, payload: object, message: str) -> None:
    with pytest.raises(CommandError, match=message):
        _seed(team.id, tmp_path / "aeo-config.json", payload)
    assert not TeamAEOConfig.objects.filter(team_id=team.id).exists()


@pytest.mark.parametrize(
    "payload",
    [
        {"target_domains": ["brand.example.net"], "competitors": [{"name": "Rival", "domians": ["other.example.net"]}]},
        {"target_domains": ["brand.example.net"], "competitor": [{"name": "Rival", "domains": ["other.example.net"]}]},
    ],
)
def test_seed_command_keeps_the_stored_config_when_a_reseed_is_rejected(
    team: Team, tmp_path: Path, payload: object
) -> None:
    path = tmp_path / "aeo-config.json"
    stored = {
        "target_domains": ["brand.example.net"],
        "competitors": [{"name": "Rival", "domains": ["rival.example.net"]}],
    }
    _seed(team.id, path, stored)

    with pytest.raises(CommandError, match=r"[Uu]nknown key\(s\)"):
        _seed(team.id, path, payload)

    assert resolve_config(team.id).competitors == (Competitor(name="Rival", domains=("rival.example.net",)),)


def test_seed_command_rejects_an_unknown_team(team: Team, tmp_path: Path) -> None:
    with pytest.raises(CommandError, match="does not exist"):
        _seed(team.id + 100_000, tmp_path / "aeo-config.json", {"target_domains": ["brand.example.net"]})
