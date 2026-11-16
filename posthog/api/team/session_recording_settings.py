"""Validators for session recording and replay settings."""

import re
from typing import TYPE_CHECKING, Any, Literal

from rest_framework import exceptions
from rest_framework.request import Request

from posthog.permissions import get_authenticator_scopes
from posthog.scopes import scopes_not_covered
from posthog.session_recordings.data_retention import VALID_RETENTION_PERIODS, validate_retention_period

from products.feature_flags.backend.session_recording_links import flag_exists_in_project

from . import settings_validation

if TYPE_CHECKING:
    from products.access_control.backend.facade.user_access_control import UserAccessControl


def can_read_feature_flags(request: Request | None) -> bool:
    """True for session auth, which carries no scopes. Access control alone limits which flags it can view."""
    scopes = get_authenticator_scopes(getattr(request, "successful_authenticator", None))
    return scopes is None or "*" in scopes or not scopes_not_covered(scopes, ["feature_flag:read"])


def validate_session_recording_linked_flag(
    value: Any, *, stored: Any, project_id: int | None, user_access_control: "UserAccessControl | None"
) -> dict | None:
    """Shared by the team and project serializers, because both endpoints can PATCH the link.

    `stored` is the link the team holds before this request.
    `project_id` is None when the request creates the project, so it has no flags to link yet.
    """
    if value is None:
        return None

    if not isinstance(value, dict):
        raise exceptions.ValidationError("Must provide a dictionary or None.")
    received_keys = value.keys()
    valid_keys = [
        {"id", "key"},
        {"id", "key", "variant"},
    ]
    if received_keys not in valid_keys:
        raise exceptions.ValidationError(
            "Must provide a dictionary with only 'id' and 'key' keys. _or_ only 'id', 'key', and 'variant' keys."
        )

    flag_id = settings_validation._replay_gate_flag_id(value["id"])
    if flag_id is None:
        raise exceptions.ValidationError("Must provide an integer 'id'.")

    # A client that sends the whole team back also sends the link it did not change. A 400 on that
    # link would reject the other edits in the same request. Accepting it reveals nothing, because a
    # GET of the team returns the stored link. The key rewrite leaves a flag that the user cannot view
    # as sent, so a match on the id alone would let a request store any key for that flag.
    # A stored link can hold its id as a numeric string, so the stored id is normalized too.
    normalized = {**value, "id": flag_id}
    if isinstance(stored, dict) and normalized == {
        **stored,
        "id": settings_validation._replay_gate_flag_id(stored.get("id")),
    }:
        return normalized

    # The SDKs treat a flag they cannot resolve as "do not record", so a link to a missing,
    # deleted, or other-project flag turns replay off for the team without an error.
    # A flag that the user cannot view gets the same error, so the error does not reveal that it exists.
    if project_id is None or not flag_exists_in_project(flag_id, project_id, user_access_control):
        raise exceptions.ValidationError(
            f"Feature flag {flag_id} doesn't exist in this project or has been deleted. Choose a different flag."
        )
    return normalized


def validate_session_recording_trigger_match_type_config(value) -> Literal["all", "any"] | None:
    if value not in ["all", "any", None]:
        raise exceptions.ValidationError(
            "Must provide a valid trigger match type. Only 'all' or 'any' or None are allowed."
        )

    return value


def validate_session_recording_trigger_groups(value) -> dict | None:
    """
    Validate V2 trigger groups configuration.

    Expected schema:
    {
        "version": 2,
        "groups": [
            {
                "id": "string",
                "name": "string" (optional),
                "sampleRate": 0.0-1.0,
                "minDurationMs": 0-30000 (optional),
                "conditions": {
                    "matchType": "any" | "all",
                    "events": ["event1", ...] (optional),
                    "urls": [{"url": "regex", "matching": "regex"}] (optional),
                    "flag": "flag-key" | {"id": 1, "key": "flag-key", "variant": "test"} (optional, single flag)
                }
            }
        ]
    }
    """
    if value is None:
        return None

    if not isinstance(value, dict):
        raise exceptions.ValidationError("Must provide a dictionary or None.")

    # Validate version
    if "version" not in value:
        raise exceptions.ValidationError("Missing required field: 'version'.")

    if value["version"] != 2:
        raise exceptions.ValidationError(f"Invalid version: {value['version']}. Only version 2 is supported.")

    # Validate groups array
    if "groups" not in value:
        raise exceptions.ValidationError("Missing required field: 'groups'.")

    if not isinstance(value["groups"], list):
        raise exceptions.ValidationError("Field 'groups' must be an array.")

    # Validate each group
    groups: list[dict[str, Any]] = []
    for idx, group in enumerate(value["groups"]):
        # Inline validation of each trigger group
        if not isinstance(group, dict):
            raise exceptions.ValidationError(f"Group {idx}: must be a dictionary.")

        # Required fields
        required_fields = ["id", "sampleRate", "conditions"]
        for field in required_fields:
            if field not in group:
                raise exceptions.ValidationError(f"Group {idx}: missing required field '{field}'.")

        # Validate sampleRate
        rate = group["sampleRate"]
        if isinstance(rate, bool) or not isinstance(rate, (int, float)) or not (0 <= rate <= 1):
            raise exceptions.ValidationError(
                f"Group {idx}: invalid sampleRate '{rate}'. Must be a number between 0 and 1."
            )

        # Validate minDurationMs if present
        if "minDurationMs" in group:
            min_duration = group["minDurationMs"]
            if isinstance(min_duration, bool) or not isinstance(min_duration, int):
                raise exceptions.ValidationError(
                    f"Group {idx}: 'minDurationMs' must be an integer, got {type(min_duration).__name__}."
                )
            if min_duration < 0 or min_duration > 30000:
                raise exceptions.ValidationError(
                    f"Group {idx}: 'minDurationMs' must be between 0 and 30000 (30 seconds). Got: {min_duration}."
                )

        # Validate conditions
        conditions = group["conditions"]
        if not isinstance(conditions, dict):
            raise exceptions.ValidationError(f"Group {idx}: field 'conditions' must be a dictionary.")

        # Validate matchType
        if "matchType" in conditions:
            if conditions["matchType"] not in ["any", "all"]:
                raise exceptions.ValidationError(
                    f"Group {idx}: invalid matchType '{conditions['matchType']}'. Must be 'any' or 'all'."
                )

        # Validate events array if present
        if "events" in conditions:
            if not isinstance(conditions["events"], list):
                raise exceptions.ValidationError(f"Group {idx}: field 'events' must be an array.")
            for event_idx, event in enumerate(conditions["events"]):
                if isinstance(event, str):
                    pass  # Simple event name is valid
                elif isinstance(event, dict):
                    if "name" not in event or not isinstance(event["name"], str):
                        raise exceptions.ValidationError(
                            f"Group {idx}: event {event_idx} object must have a string 'name' field."
                        )
                    if "properties" in event:
                        settings_validation._validate_trigger_property_filters(
                            event["properties"], f"Group {idx}, event '{event['name']}'"
                        )
                else:
                    raise exceptions.ValidationError(
                        f"Group {idx}: event {event_idx} must be a string or object with 'name'."
                    )

        # Validate URLs array if present
        if "urls" in conditions:
            if not isinstance(conditions["urls"], list):
                raise exceptions.ValidationError(f"Group {idx}: field 'urls' must be an array.")
            for url_config in conditions["urls"]:
                if not isinstance(url_config, dict):
                    raise exceptions.ValidationError(f"Group {idx}: URL config must be a dictionary.")
                if "url" not in url_config or "matching" not in url_config:
                    raise exceptions.ValidationError(f"Group {idx}: URL config must have 'url' and 'matching' fields.")
                if url_config["matching"] != "regex":
                    raise exceptions.ValidationError(
                        f"Group {idx}: URL matching must be 'regex'. Got: '{url_config['matching']}'."
                    )
                # Validate regex pattern
                try:
                    re.compile(url_config["url"])
                except re.error:
                    raise exceptions.ValidationError(
                        f"Group {idx}: invalid regex pattern in URL: '{url_config['url']}'."
                    )

        # Validate flag (single) if present
        if "flag" in conditions:
            flag_config = conditions["flag"]
            if isinstance(flag_config, str):
                pass  # Simple flag key is valid
            elif isinstance(flag_config, dict):
                # LinkedFeatureFlag object with id, key, and optional variant
                if "key" not in flag_config:
                    raise exceptions.ValidationError(f"Group {idx}: flag object must have 'key' field.")
                if not isinstance(flag_config["key"], str):
                    raise exceptions.ValidationError(f"Group {idx}: flag 'key' must be a string.")
                # id and variant are optional
                if "id" in flag_config:
                    flag_id = settings_validation._replay_gate_flag_id(flag_config["id"])
                    if flag_id is None:
                        raise exceptions.ValidationError(f"Group {idx}: flag 'id' must be an integer.")
                    group = {**group, "conditions": {**conditions, "flag": {**flag_config, "id": flag_id}}}
            elif flag_config is not None:
                raise exceptions.ValidationError(
                    f"Group {idx}: 'flag' must be a string (flag key), object (LinkedFeatureFlag), or null."
                )

        # Validate group-level property filters (shared WHERE clause for all triggers in group)
        if "properties" in conditions:
            settings_validation._validate_trigger_property_filters(conditions["properties"], f"Group {idx}")

        groups.append(group)

    # Note: All matching groups are evaluated independently
    # If any group's sample rate hits, the session is recorded (union behavior)

    # Validate fallback sample rate if present
    if "fallbackSampleRate" in value:
        rate = value["fallbackSampleRate"]
        if isinstance(rate, bool) or not isinstance(rate, (int, float)) or not (0 <= rate <= 1):
            raise exceptions.ValidationError(f"Invalid fallbackSampleRate: {rate}. Must be a number between 0 and 1.")

    return {**value, "groups": groups}


def validate_session_recording_retention_period(value) -> Literal["30d", "90d", "1y", "5y"] | None:
    if not validate_retention_period(value):
        raise exceptions.ValidationError(
            f"Must provide a valid retention period. Options are: {VALID_RETENTION_PERIODS}."
        )

    return value


def validate_session_recording_network_payload_capture_config(value) -> dict | None:
    if value is None:
        return None

    if not isinstance(value, dict):
        raise exceptions.ValidationError("Must provide a dictionary or None.")

    if not all(key in ["recordHeaders", "recordBody"] for key in value.keys()):
        raise exceptions.ValidationError(
            "Must provide a dictionary with only 'recordHeaders' and/or 'recordBody' keys."
        )

    return value


def validate_session_recording_masking_config(value) -> dict | None:
    if value is None:
        return None

    if not isinstance(value, dict):
        raise exceptions.ValidationError("Must provide a dictionary or None.")

    allowed_keys = {"maskAllInputs", "maskTextSelector", "blockSelector"}

    if not all(key in allowed_keys for key in value.keys()):
        raise exceptions.ValidationError(f"Must provide a dictionary with only known keys: {', '.join(allowed_keys)}.")

    if "maskAllInputs" in value:
        if not isinstance(value["maskAllInputs"], bool):
            raise exceptions.ValidationError("maskAllInputs must be a boolean.")

    if "maskTextSelector" in value:
        if not isinstance(value["maskTextSelector"], str):
            raise exceptions.ValidationError("maskTextSelector must be a string.")

    if "blockSelector" in value:
        if not isinstance(value["blockSelector"], str):
            raise exceptions.ValidationError("blockSelector must be a string.")

    return value


def validate_session_replay_config(value) -> dict | None:
    if value is None:
        return None

    if not isinstance(value, dict):
        raise exceptions.ValidationError("Must provide a dictionary or None.")

    known_keys = ["record_canvas", "ai_config"]
    if not all(key in known_keys for key in value.keys()):
        raise exceptions.ValidationError(
            f"Must provide a dictionary with only known keys. One or more of {', '.join(known_keys)}."
        )

    if "ai_config" in value:
        validate_session_replay_ai_summary_config(value["ai_config"])

    return value


def validate_session_replay_ai_summary_config(value: dict | None) -> dict | None:
    if value is not None:
        if not isinstance(value, dict):
            raise exceptions.ValidationError("Must provide a dictionary or None.")

        allowed_keys = [
            "included_event_properties",
            "opt_in",
            "preferred_events",
            "excluded_events",
            "important_user_properties",
        ]
        if not all(key in allowed_keys for key in value.keys()):
            raise exceptions.ValidationError(
                f"Must provide a dictionary with only allowed keys: {', '.join(allowed_keys)}."
            )

    return value
