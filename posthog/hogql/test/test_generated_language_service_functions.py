from posthog.hogql.functions.generate_language_service_functions import OUTPUT_PATH, render


def test_language_service_functions_match_generated_output() -> None:
    assert OUTPUT_PATH.read_text(encoding="utf-8") == render(), (
        "HogQL language service functions are out of sync with ALL_EXPOSED_FUNCTION_NAMES. "
        "Run: python posthog/hogql/functions/generate_language_service_functions.py"
    )
