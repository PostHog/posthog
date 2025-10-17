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
