from unittest.mock import patch

from posthog.clickhouse.client.execute import extra_settings


@patch("posthoganalytics.get_feature_flag")
def test_extra_settings_join_algorithm_valid_value(mock_get_feature_flag):
    mock_get_feature_flag.return_value = "hash"
    settings = extra_settings("some_query_id")
    assert settings == {"join_algorithm": "hash"}


@patch("posthoganalytics.get_feature_flag")
def test_extra_settings_join_algorithm_default_value(mock_get_feature_flag):
    mock_get_feature_flag.return_value = None
    settings = extra_settings("some_query_id")
    assert settings == {"join_algorithm": "default"}


@patch("posthoganalytics.get_feature_flag")
def test_extra_settings_join_algorithm_multiple_values(mock_get_feature_flag):
    mock_get_feature_flag.return_value = "hash,parallel_hash,full_sorting_merge"
    settings = extra_settings("some_query_id")
    assert settings == {"join_algorithm": "hash,parallel_hash,full_sorting_merge"}


@patch("posthoganalytics.get_feature_flag")
def test_extra_settings_join_algorithm_invalid_value(mock_get_feature_flag):
    # parallel-hash is a typo, should be parallel_hash
    mock_get_feature_flag.return_value = "hash,parallel-hash,full_sorting_merge"
    settings = extra_settings("some_query_id")
    assert settings == {"join_algorithm": "default"}
