from posthog.models.feature_flag.config import (
    FEATURE_FLAG_V2_SCHEMA_VERSION,
    FeatureFlagReleaseConditionType,
    FeatureFlagValueType,
    feature_flag_value_matches_type,
    get_v2_release_condition_property_groups,
    is_feature_flag_v2_config,
    validate_feature_flag_v2_config_shape,
)


def test_identifies_v2_feature_flag_config() -> None:
    assert is_feature_flag_v2_config({"schema_version": FEATURE_FLAG_V2_SCHEMA_VERSION})
    assert not is_feature_flag_v2_config({"groups": []})
    assert not is_feature_flag_v2_config(None)


def test_feature_flag_value_matches_declared_type() -> None:
    assert feature_flag_value_matches_type(True, FeatureFlagValueType.BOOLEAN)
    assert not feature_flag_value_matches_type("true", FeatureFlagValueType.BOOLEAN)
    assert feature_flag_value_matches_type("variant-a", FeatureFlagValueType.STRING)
    assert not feature_flag_value_matches_type(1, FeatureFlagValueType.STRING)
    assert feature_flag_value_matches_type({"button": "red"}, FeatureFlagValueType.JSON)
    assert feature_flag_value_matches_type(["a", 1, False], FeatureFlagValueType.JSON)


def test_validates_release_condition_values_against_flag_type() -> None:
    errors = validate_feature_flag_v2_config_shape(
        {
            "schema_version": FEATURE_FLAG_V2_SCHEMA_VERSION,
            "value_type": FeatureFlagValueType.BOOLEAN,
            "default_value": True,
            "release_conditions": [
                {
                    "id": "beta-users",
                    "type": FeatureFlagReleaseConditionType.TARGETED,
                    "properties": [],
                    "aggregation_group_type_index": None,
                    "value": "true",
                }
            ],
        }
    )

    assert errors == ["release_conditions[0].value must match value_type"]


def test_validates_default_value_is_required() -> None:
    errors = validate_feature_flag_v2_config_shape(
        {
            "schema_version": FEATURE_FLAG_V2_SCHEMA_VERSION,
            "value_type": FeatureFlagValueType.BOOLEAN,
            "release_conditions": [],
        }
    )

    assert errors == ["default_value is required"]


def test_validates_release_condition_shape_and_unique_ids() -> None:
    errors = validate_feature_flag_v2_config_shape(
        {
            "schema_version": FEATURE_FLAG_V2_SCHEMA_VERSION,
            "value_type": FeatureFlagValueType.BOOLEAN,
            "default_value": True,
            "release_conditions": [
                "not-an-object",
                {
                    "id": "beta-users",
                    "type": FeatureFlagReleaseConditionType.TARGETED,
                    "properties": [],
                    "aggregation_group_type_index": None,
                    "value": True,
                },
                {
                    "id": "beta-users",
                    "type": FeatureFlagReleaseConditionType.TARGETED,
                    "properties": [],
                    "aggregation_group_type_index": None,
                    "value": True,
                },
            ],
        }
    )

    assert errors == [
        "release_conditions[0] must be an object",
        "release_conditions[2].id must be unique",
    ]


def test_validates_experiment_variant_rollout_sum() -> None:
    errors = validate_feature_flag_v2_config_shape(
        {
            "schema_version": FEATURE_FLAG_V2_SCHEMA_VERSION,
            "value_type": FeatureFlagValueType.STRING,
            "default_value": "control",
            "release_conditions": [
                {
                    "id": "experiment",
                    "type": FeatureFlagReleaseConditionType.EXPERIMENT,
                    "properties": [],
                    "aggregation_group_type_index": None,
                    "rollout_percentage": 100,
                    "variants": [
                        {"key": "control", "rollout_percentage": 80, "value": "control"},
                        {"key": "test", "rollout_percentage": 10, "value": "test"},
                    ],
                }
            ],
        }
    )

    assert errors == ["release_conditions[0].variants rollout percentages must sum to 100"]


def test_gets_v2_release_condition_property_groups() -> None:
    groups = get_v2_release_condition_property_groups(
        {
            "schema_version": FEATURE_FLAG_V2_SCHEMA_VERSION,
            "value_type": FeatureFlagValueType.BOOLEAN,
            "default_value": False,
            "release_conditions": [
                {
                    "id": "beta-users",
                    "type": FeatureFlagReleaseConditionType.ROLLOUT,
                    "properties": [{"key": "beta", "type": "person", "value": "true"}],
                    "aggregation_group_type_index": None,
                    "rollout_percentage": 50,
                    "value": True,
                }
            ],
        }
    )

    assert groups == [
        {
            "properties": [{"key": "beta", "type": "person", "value": "true"}],
            "rollout_percentage": 50,
            "aggregation_group_type_index": None,
        }
    ]
