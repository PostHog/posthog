"""
Rust-powered feature flag evaluation.

This module provides a Python interface to the Rust implementation of feature flag evaluation.
The Rust implementation is significantly faster than the pure Python implementation and should
be used when performance is critical.
"""

import json
from typing import Optional, Union

from django.conf import settings

from posthog.models.team.team import Team


def get_all_feature_flags(
    team: Team,
    distinct_id: str,
    groups: Optional[dict[str, str]] = None,
    hash_key_override: Optional[str] = None,
    property_value_overrides: Optional[dict[str, Union[str, int]]] = None,
    group_property_value_overrides: Optional[dict[str, dict[str, Union[str, int]]]] = None,
    flag_keys: Optional[list[str]] = None,
) -> tuple[dict[str, Union[str, bool]], dict[str, dict], dict[str, object], bool]:
    """
    Evaluate all feature flags for a user using the Rust implementation.

    This is a convenience wrapper around get_all_feature_flags_with_details_rust that
    drops the flag_details from the return tuple to match the legacy Python API.

    Args:
        team: The team object
        distinct_id: The user's distinct ID
        groups: Optional dict of group type name -> group key
        hash_key_override: Optional hash key override ($anon_distinct_id)
        property_value_overrides: Optional dict of person property overrides
        group_property_overrides: Optional dict of group type -> properties
        flag_keys: Optional list of specific flag keys to evaluate

    Returns:
        A tuple of (flag_values, evaluation_reasons, flag_payloads, errors)
    """
    all_flags, reasons, payloads, errors, _ = get_all_feature_flags_with_details_rust(
        team,
        distinct_id,
        groups,
        hash_key_override,
        property_value_overrides,
        group_property_value_overrides,
        flag_keys,
    )
    return all_flags, reasons, payloads, errors


def get_all_feature_flags_with_details_rust(
    team: Team,
    distinct_id: str,
    groups: Optional[dict[str, str]] = None,
    hash_key_override: Optional[str] = None,
    property_value_overrides: Optional[dict[str, Union[str, int]]] = None,
    group_property_value_overrides: Optional[dict[str, dict[str, Union[str, int]]]] = None,
    flag_keys: Optional[list[str]] = None,
) -> tuple[
    dict[str, Union[str, bool]], dict[str, dict], dict[str, object], bool, Optional[dict[str, dict]]
]:
    """
    Evaluate all feature flags for a user using the Rust implementation.

    This function provides the same interface as get_all_feature_flags_with_details but
    uses the Rust implementation for better performance.

    Args:
        team: The team object
        distinct_id: The user's distinct ID
        groups: Optional dict of group type name -> group key
        hash_key_override: Optional hash key override ($anon_distinct_id)
        property_value_overrides: Optional dict of person property overrides
        group_property_overrides: Optional dict of group type -> properties
        flag_keys: Optional list of specific flag keys to evaluate

    Returns:
        A tuple of (flag_values, evaluation_reasons, flag_payloads, errors, flag_details)
    """
    try:
        from posthog_feature_flags_rs import evaluate_all_feature_flags_rust
    except ImportError:
        raise ImportError(
            "posthog_feature_flags_rs module not found. "
            "Please build the Rust extension with: cd rust/feature-flags && maturin develop --features python"
        )

    # Get database URLs from Django settings
    persons_reader_url = _get_database_url("persons_db_reader")
    persons_writer_url = _get_database_url("persons_db_writer")
    non_persons_reader_url = _get_database_url("replica")
    non_persons_writer_url = _get_database_url("default")

    # Get feature flags from cache (reusing Python implementation's caching logic)
    from posthog.models.feature_flag import (
        get_feature_flags_for_team_in_cache,
        set_feature_flags_for_team_in_cache,
    )
    from posthog.api.feature_flag import MinimalFeatureFlagSerializer

    feature_flags = get_feature_flags_for_team_in_cache(team.project_id)
    if feature_flags is None:
        feature_flags = set_feature_flags_for_team_in_cache(team.project_id)

    # Filter flags by keys if provided
    if flag_keys is not None:
        flag_keys_set = set(flag_keys)
        feature_flags = [ff for ff in feature_flags if ff.key in flag_keys_set]

    # Serialize flags to JSON for passing to Rust
    serialized_flags = MinimalFeatureFlagSerializer(feature_flags, many=True).data
    # Wrap in object with "flags" key to match FeatureFlagList struct
    feature_flags_json = json.dumps({"flags": serialized_flags})

    # Call Rust implementation
    result = evaluate_all_feature_flags_rust(
        persons_reader_url=persons_reader_url,
        persons_writer_url=persons_writer_url,
        non_persons_reader_url=non_persons_reader_url,
        non_persons_writer_url=non_persons_writer_url,
        team_id=team.id,
        project_id=team.project_id,
        distinct_id=distinct_id,
        feature_flags_json=feature_flags_json,
        groups=groups or {},
        person_property_overrides=property_value_overrides or {},
        group_property_overrides=group_property_value_overrides or {},
        hash_key_override=hash_key_override,
        flag_keys=flag_keys,
    )

    return result


def _get_database_url(db_name: str) -> str:
    """
    Get the database URL for a given database name from Django settings.

    Args:
        db_name: The database name in Django DATABASES setting

    Returns:
        PostgreSQL connection URL string
    """
    from django.db import connections

    # Try to get the database from settings
    if db_name not in connections:
        # Fallback to default database
        db_name = "default"

    db_config = settings.DATABASES.get(db_name, settings.DATABASES["default"])

    # Construct PostgreSQL URL
    user = db_config["USER"]
    password = db_config.get("PASSWORD", "")
    host = db_config["HOST"]
    port = db_config.get("PORT", 5432)
    name = db_config["NAME"]

    if password:
        return f"postgresql://{user}:{password}@{host}:{port}/{name}"
    else:
        return f"postgresql://{user}@{host}:{port}/{name}"
