from collections.abc import Sequence
from functools import lru_cache
from typing import TYPE_CHECKING

from django.utils import timezone
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

try:
    from posthog.taxonomy.taxonomy import CORE_FILTER_DEFINITIONS_BY_GROUP
except ImportError:
    CORE_FILTER_DEFINITIONS_BY_GROUP = {}

if TYPE_CHECKING:
    from posthog.taxonomy.taxonomy import CoreFilterDefinition


EVENT_SYNTHESIZER_SYSTEM_PROMPT = """
You are a synthetic value synthesizer for event property values that PostHog uses during the evaluation of their analytics AI agents. Use the provided event name, property name, and property value type to generate a set of ten SAFE REAL-WORLD values separated by a new line. Do not include any comments in your response.
<example_1>
Event name: $pageview
Property name: $browser
Property type: string
Output:
Chrome
Safari
Firefox
...
</example_1>
<example_2>
Event name: ai chat
Property name: latency
Property type: number
Output:
613
543
498
...
</example_2>
<example_3>
Event name: bill_paid
Property name: planName
Property type: string
Output:
max
pro
free
...
</example_3>
Current date is {{{current_date}}}.
""".strip()

EVENT_SYNTHESIZER_USER_PROMPT = """
Event name: {{{event_name}}}
{{#event_description}}Event description: {{.}}{{/event_description}}
Property name: {{{property_name}}}
{{#property_description}}Property description: {{.}}{{/property_description}}
{{#property_examples}}Property examples: {{.}}{{/property_examples}}
Property type: {{{property_type}}}
""".strip()

GROUP_SYNTHESIZER_SYSTEM_PROMPT = """
You are a synthetic value synthesizer for group property values that PostHog uses during the evaluation of their analytics AI agents. Use the provided group type name, property name, and property value type to generate a set of ten SAFE REAL-WORLD values separated by a new line. Do not include any comments in your response.
<example_1>
Group name: Organization
Property name: $browser
Property type: string
Output:
Chrome
Safari
Firefox
...
</example_1>
<example_2>
Group name: Team
Property name: employee count
Property type: number
Output:
4
230
10
...
</example_2>
<example_3>
Group name: Instance
Property name: planName
Property type: string
Output:
cloud
cloud-extended
legacy
evaluation
...
</example_3>
Current date is {{{current_date}}}.
""".strip()


GROUP_SYNTHESIZER_USER_PROMPT = """
Group name: {{{group_name}}}
Property name: {{{property_name}}}
{{#property_description}}Property description: {{.}}{{/property_description}}
{{#property_examples}}Property examples: {{.}}{{/property_examples}}
Property type: {{{property_type}}}
""".strip()


class PropertyValueSynthesizer:
    """Synthesizer for property values."""

    @lru_cache(maxsize=1024)
    def synthesize_event(self, event: str, prop: str, prop_type: str):
        prompt = self._format_prompt(EVENT_SYNTHESIZER_SYSTEM_PROMPT, EVENT_SYNTHESIZER_USER_PROMPT)
        taxonomy_metadata = self._find_event_metadata_in_taxonomy(event)

        chain = prompt | self._model | StrOutputParser() | self._parse_new_lines
        response = chain.invoke(
            {
                "event_name": event,
                "property_name": prop,
                "property_type": prop_type,
                "property_description": taxonomy_metadata.description if taxonomy_metadata else None,
                "property_examples": taxonomy_metadata.examples if taxonomy_metadata else None,
            }
        )

        return response

    def synthesize_group(self, group_type_name: str, prop: str, prop_type: str):
        prompt = self._format_prompt(GROUP_SYNTHESIZER_SYSTEM_PROMPT, GROUP_SYNTHESIZER_USER_PROMPT)
        taxonomy_metadata = self._find_group_metadata_in_taxonomy(group_type_name)

        chain = prompt | self._model | StrOutputParser() | self._parse_new_lines
        response = chain.invoke(
            {
                "group_name": group_type_name,
                "property_name": prop,
                "property_type": prop_type,
                "property_description": taxonomy_metadata.description if taxonomy_metadata else None,
                "property_examples": taxonomy_metadata.examples if taxonomy_metadata else None,
            }
        )

        return response

    @property
    def _model(self):
        return ChatOpenAI(
            model="gpt-5-mini",
            reasoning_effort="minimal",
            disable_streaming=True,
            max_tokens=1024,
            reasoning={"effort": "minimal", "summary": None},
            model_kwargs={"verbosity": "low"},
        )

    def _format_prompt(self, system_prompt: str, user_prompt: str):
        return ChatPromptTemplate.from_messages([("system", system_prompt), ("user", user_prompt)]).partial(
            current_date=timezone.now().strftime("%Y-%m-%d"),
        )

    def _parse_new_lines(self, text: str) -> list[str]:
        return text.split("\n")

    def _find_event_metadata_in_taxonomy(self, event: str) -> "CoreFilterDefinition" | None:
        prop_groups = {
            "event_properties",
            "session_properties",
            "metadata",
            "elements",
            "replay",
            "log_entries",
        }
        return self._find_property_metadata_in_taxonomy(prop_groups, event)

    def _find_group_metadata_in_taxonomy(self, event: str) -> "CoreFilterDefinition" | None:
        prop_groups = {
            "groups",
        }
        return self._find_property_metadata_in_taxonomy(prop_groups, event)

    def _find_property_metadata_in_taxonomy(
        self, prop_groups: Sequence[str], prop: str
    ) -> "CoreFilterDefinition" | None:
        for group in prop_groups:
            if prop_def := CORE_FILTER_DEFINITIONS_BY_GROUP[group].get(prop):
                return prop_def
        return None

    def _find_event_metadata_in_taxonomy(self, event: str) -> "CoreFilterDefinition" | None:
        return CORE_FILTER_DEFINITIONS_BY_GROUP["events"].get(event)


property_value_synthesizer = PropertyValueSynthesizer()
