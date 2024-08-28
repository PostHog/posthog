import json

from attr import dataclass

from posthog.assistant.prompt_helpers import BasePrompt
from posthog.models.team.team import Team


@dataclass
class Cohort:
    name: str
    id: int


def _hardcoded_cohorts() -> list[Cohort]:
    with open("posthog/assistant/cohorts.json") as f:
        return [Cohort(name=cohort["name"], id=cohort["id"].replace(",", "")) for cohort in json.load(f)]


class CohortsPrompt(BasePrompt):
    _team: Team

    def __init__(self, team: Team):
        self._team = team

    def generate_prompt(self) -> str:
        return self._get_xml_tag(
            "list of defined cohorts",
            "\n".join([f'name "{cohort.name}", ID {cohort.id}' for cohort in _hardcoded_cohorts()]),
        )
