from posthog.temporal.ingestion_acceptance_test.test_cases_discovery import discover_tests


def test_discovers_expected_tests() -> None:
    tests = discover_tests()

    discovered = {(t.test_class.__name__, t.method_name) for t in tests}

    assert ("TestBasicCapture", "test_capture_event_and_query") in discovered
    assert ("TestEventPropertiesCapture", "test_capture_event_with_person_properties") in discovered
