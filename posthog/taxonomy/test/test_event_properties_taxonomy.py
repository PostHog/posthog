import re
from pathlib import Path

from posthog.taxonomy.taxonomy import (
    CAMPAIGN_PROPERTIES,
    CORE_FILTER_DEFINITIONS_BY_GROUP,
    SESSION_INITIAL_PROPERTIES_ADAPTED_FROM_EVENTS,
)


def test_event_properties_includes_campaign_properties() -> None:
    keys = CORE_FILTER_DEFINITIONS_BY_GROUP["event_properties"].keys()
    for campaign_param in CAMPAIGN_PROPERTIES:
        assert campaign_param in keys


def test_initial_person_properties_set_up_correctly() -> None:
    assert (
        CORE_FILTER_DEFINITIONS_BY_GROUP["person_properties"]["$initial_referring_domain"]["label"]
        == "Initial referring domain"
    )


def test_should_have_a_session_referring_domain_property() -> None:
    prop = CORE_FILTER_DEFINITIONS_BY_GROUP["session_properties"]["$entry_referring_domain"]
    assert prop["label"] == "Entry referring domain"


def test_should_have_every_property_in_session_adopted_from_person() -> None:
    session_props = CORE_FILTER_DEFINITIONS_BY_GROUP["session_properties"].keys()
    for prop in SESSION_INITIAL_PROPERTIES_ADAPTED_FROM_EVENTS:
        assert f"$entry_{prop.replace('$', '')}" in session_props


def test_mcp_properties_mirrors_every_mcp_event_property() -> None:
    expected = {key for key in CORE_FILTER_DEFINITIONS_BY_GROUP["event_properties"] if key.startswith("$mcp_")}
    assert expected, "expected $mcp_* keys in event_properties"
    assert set(CORE_FILTER_DEFINITIONS_BY_GROUP["mcp_properties"]) == expected


MCP_SERVER_SRC = Path(__file__).parents[3] / "services" / "mcp" / "src"

# Stamped by the MCP server or its UI apps but not registered. Register them, or add
# a new one here on purpose, rather than letting a property ship without a picker entry.
KNOWN_UNREGISTERED_MCP_PROPERTIES = {
    "$mcp_skill_lookup_miss_kind",
    "$mcp_app_name",
    "$mcp_app_version",
    "$mcp_app_instance_id",
}


def test_every_stamped_mcp_property_is_registered() -> None:
    stamped = {
        match.group(1)
        for path in MCP_SERVER_SRC.rglob("*.ts")
        for match in re.finditer(r"(\$mcp_[a-z0-9_]+):", path.read_text())
    }
    assert len(stamped) > 20, "expected the MCP server source to stamp $mcp_* properties"
    registered = set(CORE_FILTER_DEFINITIONS_BY_GROUP["event_properties"])
    unregistered = stamped - registered - KNOWN_UNREGISTERED_MCP_PROPERTIES
    assert not unregistered, f"stamped in services/mcp/src but not in taxonomy.py: {sorted(unregistered)}"
    stale_exceptions = KNOWN_UNREGISTERED_MCP_PROPERTIES & registered
    assert not stale_exceptions, f"now registered, drop from the exception list: {sorted(stale_exceptions)}"
