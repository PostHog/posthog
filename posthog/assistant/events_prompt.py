import json

from attr import dataclass

from posthog.assistant.prompt_helpers import BasePrompt
from posthog.models.team.team import Team

from .hardcoded_definitions import hardcoded_prop_defs


@dataclass
class Event:
    name: str


def _hardcoded_events() -> list[Event]:
    with open("posthog/assistant/events.json") as f:
        events = json.load(f)
    return [Event(name=event["name"]) for event in events]


class EventsPropmpt(BasePrompt):
    _team: Team

    def __init__(self, team: Team):
        super().__init__()
        self._team = team

    def generate_prompt(self) -> str:
        events = _hardcoded_events()

        event_description_mapping = {
            "$identify": "Identifies an anonymous user. This event doesn't show how many users you have but rather how many users used an account."
        }

        tags = []
        for event in events:
            event_tag = event.name
            if event.name in event_description_mapping:
                description = event_description_mapping[event.name]
                event_tag += f" - {description}"
            elif event.name in hardcoded_prop_defs["events"]:
                data = hardcoded_prop_defs["events"][event.name]
                event_tag += f" - {data['label']}. {data['description']}"
                if "examples" in data:
                    event_tag += f" Examples: {data['examples']}."
            tags.append(self._clean_line(event_tag))

        tag_name = "list of available events for filtering"
        return self._get_xml_tag(tag_name, "\n".join(sorted(tags)))
