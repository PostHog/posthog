from __future__ import annotations

import math
from enum import StrEnum
from typing import NotRequired, TypedDict, TypeGuard

FEATURE_FLAG_V2_SCHEMA_VERSION = 2

type JsonPrimitive = str | int | float | bool | None
type JsonValue = JsonPrimitive | list[JsonValue] | dict[str, JsonValue]


class FeatureFlagValueType(StrEnum):
    BOOLEAN = "boolean"
    STRING = "string"
    JSON = "json"


class FeatureFlagReleaseConditionType(StrEnum):
    TARGETED = "targeted"
    ROLLOUT = "rollout"
    EXPERIMENT = "experiment"


class FeatureFlagV2Variant(TypedDict):
    key: str
    rollout_percentage: float
    value: JsonValue
    name: NotRequired[str | None]


class FeatureFlagV2ReleaseCondition(TypedDict):
    id: str
    type: str
    properties: list[dict[str, JsonValue]]
    aggregation_group_type_index: int | None
    value: NotRequired[JsonValue]
    rollout_percentage: NotRequired[float | None]
    variants: NotRequired[list[FeatureFlagV2Variant]]
    name: NotRequired[str | None]
    description: NotRequired[str | None]


class FeatureFlagV2Config(TypedDict):
    schema_version: int
    value_type: str
    default_value: JsonValue
    release_conditions: list[FeatureFlagV2ReleaseCondition]
    aggregation_group_type_index: NotRequired[int | None]


def is_feature_flag_v2_config(filters: object) -> TypeGuard[FeatureFlagV2Config]:
    return isinstance(filters, dict) and filters.get("schema_version") == FEATURE_FLAG_V2_SCHEMA_VERSION


def is_json_value(value: object) -> TypeGuard[JsonValue]:
    if value is None or isinstance(value, (str, bool, int)):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, list):
        return all(is_json_value(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and is_json_value(item) for key, item in value.items())
    return False


def feature_flag_value_matches_type(value: object, value_type: str) -> bool:
    if value_type == FeatureFlagValueType.BOOLEAN:
        return isinstance(value, bool)
    if value_type == FeatureFlagValueType.STRING:
        return isinstance(value, str)
    if value_type == FeatureFlagValueType.JSON:
        return is_json_value(value)
    return False


def validate_feature_flag_v2_config_shape(config: FeatureFlagV2Config) -> list[str]:
    errors: list[str] = []
    value_type = config.get("value_type")

    if value_type not in FeatureFlagValueType:
        errors.append("value_type must be one of boolean, string, or json")
        return errors

    if not feature_flag_value_matches_type(config.get("default_value"), value_type):
        errors.append("default_value must match value_type")

    release_conditions = config.get("release_conditions")
    if not isinstance(release_conditions, list):
        errors.append("release_conditions must be a list")
        return errors

    for index, condition in enumerate(release_conditions):
        condition_type = condition.get("type")
        if condition_type not in FeatureFlagReleaseConditionType:
            errors.append(f"release_conditions[{index}].type is invalid")
            continue

        properties = condition.get("properties")
        if not isinstance(properties, list):
            errors.append(f"release_conditions[{index}].properties must be a list")

        aggregation_group_type_index = condition.get("aggregation_group_type_index")
        if aggregation_group_type_index is not None and (
            isinstance(aggregation_group_type_index, bool) or not isinstance(aggregation_group_type_index, int)
        ):
            errors.append(f"release_conditions[{index}].aggregation_group_type_index must be an integer or null")

        if condition_type in (FeatureFlagReleaseConditionType.TARGETED, FeatureFlagReleaseConditionType.ROLLOUT):
            if "value" not in condition:
                errors.append(f"release_conditions[{index}].value is required")
            elif not feature_flag_value_matches_type(condition.get("value"), value_type):
                errors.append(f"release_conditions[{index}].value must match value_type")

        if condition_type in (FeatureFlagReleaseConditionType.ROLLOUT, FeatureFlagReleaseConditionType.EXPERIMENT):
            _validate_rollout_percentage(
                condition.get("rollout_percentage"),
                f"release_conditions[{index}].rollout_percentage",
                errors,
            )

        if condition_type == FeatureFlagReleaseConditionType.EXPERIMENT:
            variants = condition.get("variants")
            if not isinstance(variants, list) or len(variants) == 0:
                errors.append(f"release_conditions[{index}].variants must be a non-empty list")
                continue

            rollout_sum = 0.0
            seen_variant_keys: set[str] = set()
            for variant_index, variant in enumerate(variants):
                key = variant.get("key")
                if not isinstance(key, str) or not key:
                    errors.append(f"release_conditions[{index}].variants[{variant_index}].key is required")
                elif key in seen_variant_keys:
                    errors.append(f"release_conditions[{index}].variants[{variant_index}].key must be unique")
                else:
                    seen_variant_keys.add(key)

                rollout_percentage = variant.get("rollout_percentage")
                _validate_rollout_percentage(
                    rollout_percentage,
                    f"release_conditions[{index}].variants[{variant_index}].rollout_percentage",
                    errors,
                )
                if isinstance(rollout_percentage, (int, float)) and not isinstance(rollout_percentage, bool):
                    rollout_sum += float(rollout_percentage)

                if not feature_flag_value_matches_type(variant.get("value"), value_type):
                    errors.append(f"release_conditions[{index}].variants[{variant_index}].value must match value_type")

            if not math.isclose(rollout_sum, 100.0):
                errors.append(f"release_conditions[{index}].variants rollout percentages must sum to 100")

    return errors


def get_v2_release_condition_property_groups(config: FeatureFlagV2Config) -> list[dict[str, object]]:
    groups: list[dict[str, object]] = []
    for condition in config.get("release_conditions", []):
        groups.append(
            {
                "properties": condition.get("properties", []),
                "aggregation_group_type_index": condition.get("aggregation_group_type_index"),
            }
        )
    return groups


def _validate_rollout_percentage(value: object, path: str, errors: list[str]) -> None:
    if value is None:
        errors.append(f"{path} is required")
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        errors.append(f"{path} must be a number")
        return
    if not math.isfinite(value):
        errors.append(f"{path} must be finite")
        return
    if value < 0 or value > 100:
        errors.append(f"{path} must be between 0 and 100")
