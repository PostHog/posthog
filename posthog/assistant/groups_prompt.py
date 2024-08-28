from posthog.assistant.prompt_helpers import BasePrompt
from posthog.models.team.team import Team


class GroupsPrompt(BasePrompt):
    _team: Team

    def __init__(self, team: Team):
        self._team = team

    def generate_prompt(self) -> str:
        user_groups = [("organization", 0), ("instance", 1), ("project", 2)]
        return self._get_xml_tag(
            "list of defined groups", "\n".join([f'name "{name}", index {index}' for name, index in user_groups])
        )
