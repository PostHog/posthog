import collections
import json

from attr import dataclass

from posthog.models.property_definition import PropertyDefinition, PropertyType
from posthog.models.team.team import Team

from .hardcoded_definitions import hardcoded_prop_defs


@dataclass
class Event:
    name: str


def _hardcoded_events() -> list[Event]:
    with open("posthog/assistant/events.json") as f:
        events = json.load(f)
    return [Event(name=event["name"]) for event in events]


@dataclass
class Cohort:
    name: str
    id: int


def _hardcoded_cohorts() -> list[Cohort]:
    with open("posthog/assistant/cohorts.json") as f:
        return [Cohort(name=cohort["name"], id=cohort["id"].replace(",", "")) for cohort in json.load(f)]


@dataclass
class Property:
    type: PropertyDefinition.Type
    name: str
    property_type: PropertyType


def _hardcoded_properties() -> list[Property]:
    with open("posthog/assistant/properties.json") as f:
        properties = json.load(f)
    return [
        Property(
            type=PropertyDefinition.Type(int(prop["type"])),
            name=prop["name"],
            property_type=PropertyType(prop["property_type"]),
        )
        for prop in properties
    ]


class TeamPrompt:
    _team: Team

    def __init__(self, team: Team):
        super().__init__()
        self._team = team

    @classmethod
    def get_properties_tag_name(self, property_name: str) -> str:
        return f"list of {property_name.lower()} property definitions by a type"

    def _clean_line(self, line: str) -> str:
        return line.replace("\n", " ")

    def _get_xml_tag(self, tag_name: str, content: str) -> str:
        return f"\n<{tag_name}>\n{content.strip()}\n</{tag_name}>\n"

    def _generate_cohorts_prompt(self) -> str:
        return self._get_xml_tag(
            "list of defined cohorts",
            "\n".join([f'name "{cohort.name}", ID {cohort.id}' for cohort in _hardcoded_cohorts()]),
        )

    def _generate_events_prompt(self) -> str:
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

    def _generate_groups_prompt(self) -> str:
        user_groups = [("organization", 0), ("instance", 1), ("project", 2)]
        return self._get_xml_tag(
            "list of defined groups", "\n".join([f'name "{name}", index {index}' for name, index in user_groups])
        )

    def _join_property_tags(self, tag_name: str, properties_by_type: dict[str, list[str]]) -> str:
        if any(prop_by_type for prop_by_type in properties_by_type.values()):
            tags = "\n".join(
                self._get_xml_tag(prop_type, "\n".join(tags)) for prop_type, tags in properties_by_type.items()
            )
            return self._get_xml_tag(tag_name, tags) + "\n"
        return ""

    def _get_property_type(self, prop: Property) -> str:
        if prop.name.startswith("$feature/"):
            return "feature"
        return prop.type.label.lower()

    def _generate_properties_prompt(self) -> str:
        # props = (
        #     PropertyDefinition.objects.filter(team=self._team, type=property_type)
        #     .exclude(name__icontains="__")
        #     .exclude(name__icontains="phjs")
        #     .exclude(name__startswith="$survey_dismissed/")
        #     .exclude(name__startswith="$survey_responded/")
        #     .exclude(name__startswith="partial_filter_chosen_")
        #     .exclude(name__startswith="changed_action_")
        #     .exclude(name__icontains="window-id-")
        #     .exclude(name__startswith="changed_event_")
        # )
        properties = _hardcoded_properties()

        key_mapping = {
            "event": "event_properties",
        }

        tags: dict[str, dict[str, list[str]]] = collections.defaultdict(lambda: collections.defaultdict(list))

        for prop in properties:
            category = self._get_property_type(prop)
            if category in ["group", "session"]:
                continue

            prop_tag = prop.name

            if category in key_mapping and prop.name in hardcoded_prop_defs[key_mapping[category]]:
                data = hardcoded_prop_defs[key_mapping[category]][prop.name]
                if "label" in data:
                    prop_tag += f" - {data['label']}."
                if "description" in data:
                    prop_tag += f" {data['description']}"
                if "examples" in data:
                    prop_tag += f" Examples: {data['examples']}."

            tags[category][prop.property_type].append(self._clean_line(prop_tag))

        # Session hardcoded properties
        for key, defs in hardcoded_prop_defs["session_properties"].items():
            prop_tag += f"{key} - {defs['label']}. {defs['description']}."
            if "examples" in defs:
                prop_tag += f" Examples: {defs['examples']}."
            tags["session"][prop.property_type].append(self._clean_line(prop_tag))

        prompt = "\n".join(
            [self._join_property_tags(self.get_properties_tag_name(category), tags[category]) for category in tags],
        )

        return prompt

    def generate_prompt(self) -> str:
        return "".join(
            [
                self._generate_groups_prompt(),
                self._generate_events_prompt(),
                self._generate_properties_prompt(),
            ]
        )
