import os

import defusedxml.ElementTree as ET
from parameterized import parameterized

from posthog.schema import PropertyOperator

from posthog.taxonomy.taxonomy import CORE_FILTER_DEFINITIONS_BY_GROUP, visible_definitions

from products.cdp.backend.prompts import (
    UNSUPPORTED_FILTER_OPERATORS,
    render_event_property_taxonomy,
    render_event_taxonomy,
    render_filter_operator_taxonomy,
    render_filters_system_prompt,
    render_person_property_taxonomy,
)

from ee.hogai.summarizers.property_filters import PROPERTY_FILTER_VERBOSE_NAME


def _texts(xml: str, tag: str) -> set[str]:
    return {element.text or "" for element in ET.fromstring(xml).iter(tag)}


class TestTaxonomyPrompts:
    def test_render_covers_every_visible_taxonomy_entry(self):
        assert _texts(render_event_taxonomy(), "name") == {name for name, _ in visible_definitions("events")}

    def test_render_person_properties_covers_every_visible_non_virtual_entry(self):
        # Virtual properties are excluded because a filter on one never matches at CDP runtime.
        assert _texts(render_person_property_taxonomy(), "name") == {
            name for name, definition in visible_definitions("person_properties") if not definition.get("virtual")
        }

    def test_render_event_properties_excludes_virtual_and_distinct_id(self):
        # Both compile to a lookup CDP never populates: a virtual property throws at runtime, and
        # `distinct_id` silently evaluates false.
        names = _texts(render_event_property_taxonomy(), "name")

        assert names == {
            name
            for name, definition in visible_definitions("event_properties")
            if not definition.get("virtual") and name != "distinct_id"
        }
        # Anchored on a literal, so dropping the exclusion fails here instead of moving in lockstep
        # with the derived set above.
        assert CORE_FILTER_DEFINITIONS_BY_GROUP["event_properties"]["$virt_is_bot"].get("virtual")
        assert "$virt_is_bot" not in names
        assert "distinct_id" not in names

    @parameterized.expand(
        [
            ("events", render_event_taxonomy, "$autocapture"),
            ("event_properties", render_event_property_taxonomy, "$exception_steps"),
            ("person_properties", render_person_property_taxonomy, "$initial_person_info"),
        ]
    )
    def test_render_omits_hidden_taxonomy_entries(self, group, render, hidden_name):
        # Asserted against literal names rather than `visible_definitions`, which the renderers
        # also call: if that filter stopped excluding hidden entries, both sides would move
        # together and the completeness test above would still pass.
        assert hidden_name in CORE_FILTER_DEFINITIONS_BY_GROUP[group]
        assert hidden_name not in _texts(render(), "name")

    def test_render_event_taxonomy_carries_descriptions_and_examples(self):
        events = {event.findtext("name"): event for event in ET.fromstring(render_event_taxonomy()).iter("event")}

        identify = CORE_FILTER_DEFINITIONS_BY_GROUP["events"]["$identify"]
        # `$identify` has both, so this also pins the `description_llm` precedence.
        assert events["$identify"].findtext("description") == identify["description_llm"]
        assert (
            events["$pageview"].findtext("description")
            == CORE_FILTER_DEFINITIONS_BY_GROUP["events"]["$pageview"]["description"]
        )
        assert events["$csp_violation"].findtext("examples")

    @parameterized.expand(
        [
            ("email", True),  # no counterpart in <event_property_taxonomy>
            ("distinct_id", True),  # excluded from the event block, so this is where it is described
            ("$browser", False),  # a copy; the usage note sends the model to <event_property_taxonomy>
            ("$initial_browser", False),
        ]
    )
    def test_render_person_properties_describes_only_names_the_event_section_lacks(self, name, has_description):
        properties = {
            prop.findtext("name"): prop for prop in ET.fromstring(render_person_property_taxonomy()).iter("property")
        }

        assert (properties[name].findtext("description") is not None) == has_description

    def test_render_operators_uses_wire_values(self):
        values = _texts(render_filter_operator_taxonomy("destination"), "value")

        assert values == {
            operator.value for operator in PROPERTY_FILTER_VERBOSE_NAME if operator not in UNSUPPORTED_FILTER_OPERATORS
        }
        # These three have to stay reachable: they are the operators the model cannot express by
        # any other means, so losing them from the prompt silently narrows what it can filter on.
        assert {
            PropertyOperator.STARTS_WITH.value,
            PropertyOperator.ENDS_WITH.value,
            PropertyOperator.SEMVER_GTE.value,
        } <= values

    def test_render_operators_omits_operators_hog_functions_cannot_compile(self):
        assert PropertyOperator.FLAG_EVALUATES_TO in UNSUPPORTED_FILTER_OPERATORS
        assert PropertyOperator.FLAG_EVALUATES_TO.value not in _texts(
            render_filter_operator_taxonomy("destination"), "value"
        )

    @parameterized.expand([("site_destination",), ("site_app",)])
    def test_render_operators_omits_js_unsupported_operators_for_transpiled_types(self, function_type):
        # Listed literally, not read from the renderer's own exclusion set, so a family member that
        # stopped being excluded fails here rather than moving both sides together.
        broken_on_site = {
            PropertyOperator.ICONTAINS_MULTI.value,
            PropertyOperator.NOT_ICONTAINS_MULTI.value,
            PropertyOperator.SEMVER_EQ.value,
            PropertyOperator.SEMVER_NEQ.value,
            PropertyOperator.SEMVER_GT.value,
            PropertyOperator.SEMVER_GTE.value,
            PropertyOperator.SEMVER_LT.value,
            PropertyOperator.SEMVER_LTE.value,
            PropertyOperator.SEMVER_TILDE.value,
            PropertyOperator.SEMVER_CARET.value,
            PropertyOperator.SEMVER_WILDCARD.value,
        }

        assert broken_on_site.isdisjoint(_texts(render_filter_operator_taxonomy(function_type), "value"))
        # Scoped to the transpiled types: the bytecode STL defines both functions, so a destination
        # keeps every one of them.
        assert broken_on_site <= _texts(render_filter_operator_taxonomy("destination"), "value")

    @parameterized.expand(
        [
            ("transformation", False),
            ("transformation_log", False),
            ("destination", True),
            ("site_destination", True),
        ]
    )
    def test_system_prompt_swaps_the_person_block_for_a_scope_note_without_person_globals(
        self, function_type, has_person_globals
    ):
        prompt = render_filters_system_prompt(function_type, "{}")

        assert ("<person_property_taxonomy>" in prompt) == has_person_globals
        assert ("<filter_scope>" in prompt) != has_person_globals
        assert "<event_property_taxonomy>" in prompt

    def test_system_prompt_keeps_one_shared_prefix_up_to_the_person_block(self):
        # The taxonomy ahead of that block is what the provider's prompt cache can reuse across
        # function types, so a type-specific section must never be spliced in before it.
        destination = render_filters_system_prompt("destination", "{}")
        transformation = render_filters_system_prompt("transformation", "{}")
        shared = len(os.path.commonprefix([destination, transformation]))

        assert shared > destination.index("<person_property_taxonomy>") - 1
