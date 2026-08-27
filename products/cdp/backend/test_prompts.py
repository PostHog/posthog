import defusedxml.ElementTree as ET
from parameterized import parameterized

from posthog.schema import PropertyOperator

from posthog.taxonomy.taxonomy import CORE_FILTER_DEFINITIONS_BY_GROUP, visible_definitions

from products.cdp.backend.prompts import (
    UNSUPPORTED_FILTER_OPERATORS,
    render_event_property_taxonomy,
    render_event_taxonomy,
    render_filter_operator_taxonomy,
    render_person_property_taxonomy,
)

from ee.hogai.summarizers.property_filters import PROPERTY_FILTER_VERBOSE_NAME


def _texts(xml: str, tag: str) -> set[str]:
    return {element.text or "" for element in ET.fromstring(xml).iter(tag)}


class TestTaxonomyPrompts:
    @parameterized.expand(
        [
            ("events", render_event_taxonomy),
            ("event_properties", render_event_property_taxonomy),
        ]
    )
    def test_render_covers_every_visible_taxonomy_entry(self, group, render):
        # Virtual entries are excluded because a filter on one fails at CDP runtime; the events
        # group carries none, so this stays a full-coverage check for that renderer.
        assert _texts(render(), "name") == {
            name for name, definition in visible_definitions(group) if not definition.get("virtual")
        }

    def test_render_event_properties_omit_virtual_entries(self):
        # A virtual event property like `$virt_is_bot` compiles to a top-level global the CDP filter
        # runtime never provides, so a saved filter on one fails instead of matching. Asserted
        # against a literal name, not the renderer's own `virtual` check, so dropping the exclusion
        # fails here rather than moving in lockstep with the completeness test above.
        assert CORE_FILTER_DEFINITIONS_BY_GROUP["event_properties"]["$virt_is_bot"].get("virtual")
        assert "$virt_is_bot" not in _texts(render_event_property_taxonomy(), "name")

    def test_render_person_properties_covers_every_visible_non_virtual_entry(self):
        # Virtual properties are excluded because a filter on one never matches at CDP runtime.
        assert _texts(render_person_property_taxonomy("destination"), "name") == {
            name for name, definition in visible_definitions("person_properties") if not definition.get("virtual")
        }

    @parameterized.expand(["transformation", "transformation_log"])
    def test_render_person_properties_empty_for_types_without_a_person(self, function_type):
        # These types run before person resolution, so a person filter evaluates against a null
        # person and never matches. The renderer offers no person properties for them; a
        # destination, whose runtime populates person, still gets the full set.
        assert "<property>" not in render_person_property_taxonomy(function_type)
        assert "email" in _texts(render_person_property_taxonomy("destination"), "name")

    @parameterized.expand(
        [
            ("events", render_event_taxonomy, "$autocapture"),
            ("event_properties", render_event_property_taxonomy, "$exception_steps"),
            ("person_properties", lambda: render_person_property_taxonomy("destination"), "$initial_person_info"),
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

    def test_render_person_properties_describes_only_names_the_event_section_lacks(self):
        # `email` has no counterpart in <event_property_taxonomy>, so this block is the only place
        # the model can read its meaning. `$browser` is a copy, and the usage note sends the model
        # next door for it.
        properties = {
            prop.findtext("name"): prop
            for prop in ET.fromstring(render_person_property_taxonomy("destination")).iter("property")
        }

        assert properties["email"].findtext("description")
        assert properties["$browser"].findtext("description") is None
        assert properties["$initial_browser"].findtext("description") is None

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

    @parameterized.expand(["site_destination", "site_app"])
    def test_render_operators_omits_operators_that_break_transpiled_filters(self, function_type):
        # Site types transpile filters to JavaScript, whose standard library defines neither
        # `sortableSemver` (semver operators) nor `multiSearchAnyCaseInsensitive` (multi-contains).
        # A saved filter using one throws at runtime, so these must not reach the model for a site
        # type. Every other type compiles to bytecode, which defines both, so they stay offered.
        # Asserted against literal names, not the renderer's own exclusion set, so a change that
        # stopped excluding them would fail here instead of moving both sides together.
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
        site_values = _texts(render_filter_operator_taxonomy(function_type), "value")
        destination_values = _texts(render_filter_operator_taxonomy("destination"), "value")

        assert broken_on_site.isdisjoint(site_values)
        # Scoped to site types: the bytecode path keeps every one of them.
        assert broken_on_site <= destination_values
