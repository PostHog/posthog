import json
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from posthog.models.scoping.manager import TeamScopeError

from products.aeo.backend.facade.api import update_config
from products.aeo.backend.facade.contracts import AEOConfig, AEOConfigError, Competitor

CONFIG_KEYS = frozenset({"target_domains", "brand_names", "competitors"})
COMPETITOR_KEYS = frozenset({"name", "domains"})


def _strings(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise CommandError(f"{field} must be a list of strings")
    return tuple(value)


def _competitor(item: object, index: int) -> Competitor:
    if not isinstance(item, dict) or not isinstance(item.get("name"), str):
        raise CommandError(f"competitors[{index}] must be an object with a name and a list of domains")
    if unknown := sorted(set(item) - COMPETITOR_KEYS):
        raise CommandError(
            f"competitors[{index}] has unknown key(s) {unknown}; a competitor may hold {sorted(COMPETITOR_KEYS)}"
        )
    return Competitor(name=item["name"], domains=_strings(item.get("domains", []), f"competitors[{index}].domains"))


def parse_config(payload: object) -> AEOConfig:
    """The file's shape check. A key the file misspells would otherwise read as
    missing and store a config with that detection turned off."""
    if not isinstance(payload, dict):
        raise CommandError("The config file must hold a JSON object")
    if unknown := sorted(set(payload) - CONFIG_KEYS):
        raise CommandError(f"Unknown key(s) {unknown}; the file may hold {sorted(CONFIG_KEYS)}")
    competitors = payload.get("competitors", [])
    if not isinstance(competitors, list):
        raise CommandError("competitors must be a list of objects, each with a name and a list of domains")
    return AEOConfig(
        target_domains=_strings(payload.get("target_domains", []), "target_domains"),
        brand_names=_strings(payload.get("brand_names", []), "brand_names"),
        competitors=tuple(_competitor(item, index) for index, item in enumerate(competitors)),
    )


class Command(BaseCommand):
    help = (
        "Load a team's AEO brand config from a JSON file: "
        '{"target_domains": [...], "brand_names": [...], "competitors": [{"name": ..., "domains": [...]}]}.'
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument("--file", type=str, required=True, help="Path to the JSON config file.")

    def handle(self, *args: Any, **options: Any) -> None:
        path = Path(options["file"])
        try:
            payload = json.loads(path.read_text())
        except (OSError, ValueError) as error:
            raise CommandError(f"Could not read {path}: {error}") from error

        try:
            config = update_config(options["team_id"], parse_config(payload))
        except TeamScopeError as error:
            raise CommandError(f"Team {options['team_id']} does not exist") from error
        except AEOConfigError as error:
            raise CommandError(f"Config rejected: {error}") from error

        self.stdout.write(
            self.style.SUCCESS(
                f"Stored config for team {options['team_id']}: "
                f"{len(config.target_domains)} target domain(s), {len(config.brand_names)} brand name(s), "
                f"{len(config.competitors)} competitor(s)"
            )
        )
