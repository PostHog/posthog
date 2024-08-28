import collections
import json

from attr import dataclass

from posthog.assistant.prompt_helpers import BasePrompt
from posthog.models.property_definition import PropertyDefinition, PropertyType
from posthog.models.team.team import Team

from .hardcoded_definitions import hardcoded_prop_defs


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


class PropertiesPrompt(BasePrompt):
    _team: Team

    def __init__(self, team: Team):
        super().__init__()
        self._team = team

    @classmethod
    def get_tag_name(self, property_name: str) -> str:
        return f"list of {property_name.lower()} property definitions by a type"

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

    def generate_prompt(self) -> str:
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
            [self._join_property_tags(self.get_tag_name(category), tags[category]) for category in tags],
        )

        return prompt
