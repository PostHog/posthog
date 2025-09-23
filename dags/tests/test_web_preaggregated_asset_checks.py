from dags.web_preaggregated_asset_checks import create_accuracy_check_result


def test_create_accuracy_check_result_handles_integer_values_for_dagster():
    """
    Test that create_accuracy_check_result properly handles integer values that would
    cause Dagster's MetadataValue.float() to fail with ParameterCheckError.

    This test ensures our fix will continue to work - if the float() conversion is ever
    removed, this test will fail when Dagster validates the parameters.
    """
    comparison_data = {
        "team_id": 123,
        "date_from": "2023-01-01",
        "date_to": "2023-01-07",
        "table_version": "v2",
        "metrics": {
            "unique_visitors": {
                "pre_aggregated": 0,
                "regular": 0,
                "pct_difference": 0,
                "within_tolerance": True,
            }
        },
        "all_within_tolerance": True,
        "tolerance_pct": 1.0,
        "timing": {"pre_aggregated": 0.5, "regular": 1.2},
    }

    # This should NOT raise: ParameterCheckError: Param "value" is not a float. Got 0 which is type <class 'int'>
    # If our fix is removed, this will fail with that exact error
    result = create_accuracy_check_result(comparison_data, team_id=123, table_version="v2")

    # Verify the function completed successfully
    assert result is not None
    assert result.passed is True
    assert result.metadata is not None

    # Verify the problematic metadata fields were created successfully
    assert "unique_visitors_pre_aggregated" in result.metadata
    assert "unique_visitors_regular" in result.metadata
    assert "unique_visitors_percentage_difference" in result.metadata
