from posthog.taxonomy.property_values_deny import PROPERTY_VALUES_DENY


def test_includes_known_high_cardinality_offenders() -> None:
    expected = {
        "$insert_id",
        "$set",
        "$set_once",
        "$cymbal_errors",
        "$creator_event_uuid",
        "$initial_geoip_longitude",
        "$initial_geoip_latitude",
        "$survey_last_seen_date",
    }
    missing = expected - PROPERTY_VALUES_DENY
    assert not missing, f"deny-list missing expected keys: {sorted(missing)}"


def test_does_not_block_useful_autocomplete_keys() -> None:
    must_keep = {
        "$browser",
        "$os",
        "$current_url",
        "$pathname",
        "$initial_geoip_country_name",
        "$initial_geoip_city_name",
        "utm_source",
        "utm_campaign",
    }
    leaked = must_keep & PROPERTY_VALUES_DENY
    assert not leaked, f"deny-list should not contain user-facing keys: {sorted(leaked)}"


def test_is_a_frozenset() -> None:
    assert isinstance(PROPERTY_VALUES_DENY, frozenset)
