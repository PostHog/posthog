from posthog.temporal.ingestion_acceptance_test.test_cases_discovery import discover_tests


def test_discovers_expected_tests() -> None:
    tests = discover_tests()

    discovered = {(t.test_class.__name__, t.method_name) for t in tests}

    # Basic capture tests
    assert ("TestBasicCapture", "test_capture_event") in discovered
    assert ("TestBasicCapture", "test_capture_event_with_properties") in discovered

    # Person properties tests
    assert ("TestPersonPropertiesCapture", "test_set_person_properties") in discovered
    assert ("TestPersonPropertiesCapture", "test_set_once_person_properties") in discovered
    assert ("TestPersonPropertiesCapture", "test_unset_person_properties") in discovered
    assert ("TestPersonPropertiesCapture", "test_combined_set_set_once_unset") in discovered

    # Alias test
    assert ("TestAlias", "test_alias_merges_events_from_different_distinct_ids") in discovered

    # Merge test
    assert ("TestMergeDangerously", "test_merge_combines_two_persons_events") in discovered

    assert len(tests) == 8
