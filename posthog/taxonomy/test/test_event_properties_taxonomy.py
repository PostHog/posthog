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


# An unprefixed key applies to every project, so it renames and re-describes a property
# a customer already owns. Keys below predate the rule; the set must only shrink.
UNPREFIXED_EVENT_PROPERTIES = {
    "build",
    "currency",
    "distinct_id",
    "duration_ms",
    "from_background",
    "is_error",
    "mcp_client_name",
    "mcp_client_version",
    "mcp_consumer",
    "mcp_conversation_id",
    "mcp_mode",
    "mcp_oauth_client_name",
    "mcp_protocol_version",
    "mcp_runtime",
    "mcp_session_client_name",
    "mcp_session_client_version",
    "mcp_session_consumer",
    "mcp_session_id",
    "mcp_session_protocol_version",
    "mcp_session_vendor_client",
    "mcp_transport",
    "mcp_vendor_client",
    "mcp_version",
    "previous_build",
    "previous_version",
    "referring_application",
    "resource_name",
    "revenue",
    "token",
    "tool_name",
    "url",
    "utm_name",
    "version",
}


def test_new_event_properties_are_dollar_prefixed() -> None:
    unprefixed = {
        key
        for key in CORE_FILTER_DEFINITIONS_BY_GROUP["event_properties"]
        if not key.startswith("$") and key not in CAMPAIGN_PROPERTIES
    }
    assert unprefixed <= UNPREFIXED_EVENT_PROPERTIES, (
        f"{sorted(unprefixed - UNPREFIXED_EVENT_PROPERTIES)} must start with '$'. PostHog properties in the core "
        "taxonomy apply to every project, so an unprefixed name gives a customer property of the same name our "
        "label, our description, and the PostHog icon."
    )
