from typing import Any, Union
from posthog.schema import (
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldSelectConfig,
    SourceFieldSwitchGroupConfig,
    SourceFieldOauthConfig,
    SourceFieldFileUploadConfig,
)

SourceFieldConfig = Union[
    SourceFieldInputConfig,
    SourceFieldSelectConfig,
    SourceFieldSwitchGroupConfig,
    SourceFieldOauthConfig,
    SourceFieldFileUploadConfig,
]


def transform_payload_to_job_inputs(source_config: SourceConfig, payload: dict[str, Any]) -> dict[str, Any]:
    """
    Transform frontend payload to job_inputs format.

    Frontend payload structure (from sourceWizardLogic):
    {
        "prefix": "optional_prefix",
        "payload": {
            "field1": "value1",
            "switch-group-field": {
                "enabled": True,
                "sub_field1": "value1",
                "sub_field2": "value2"
            },
            "select-field": {
                "selection": "option1",
                "option_field1": "value1"
            },
            "file-field": [File object] # Gets processed to JSON
        }
    }

    Backend job_inputs structure:
    {
        "field1": "value1",
        "switch-group-field": {
            "enabled": True,
            "sub_field1": "value1",
            "sub_field2": "value2"
        },
        "select-field": "option1",  # Flattened selection
        "option_field1": "value1",  # Option fields promoted to top level
        "file-field": {...}  # Parsed JSON content
    }
    """
    job_inputs = {}
    form_payload = payload.get("payload", {})

    for field in source_config.fields:
        field_value = form_payload.get(field.name)
        if field_value is None:
            continue

        if isinstance(field, SourceFieldInputConfig):
            # Simple field mapping
            job_inputs[field.name] = field_value

        elif isinstance(field, SourceFieldSwitchGroupConfig):
            # Handle switch groups (like SSH tunnels)
            job_inputs[field.name] = _transform_switch_group(field, field_value)

        elif isinstance(field, SourceFieldSelectConfig):
            # Handle selects with conditional option fields
            _transform_select_field(field, field_value, job_inputs)

        elif isinstance(field, SourceFieldOauthConfig):
            # OAuth fields map directly
            job_inputs[field.name] = field_value

        elif isinstance(field, SourceFieldFileUploadConfig):
            # File uploads should already be processed by frontend
            # Frontend handles FileReader and JSON.parse
            job_inputs[field.name] = field_value

    return job_inputs


def _transform_switch_group(field: SourceFieldSwitchGroupConfig, field_value: dict[str, Any]) -> dict[str, Any]:
    """
    Transform switch group field (like SSH tunnel configuration).

    Frontend: {"enabled": True, "sub_field": "value"}
    Backend: {"enabled": True, "sub_field": "value"}  # Same structure
    """
    result = {}

    # Handle enabled flag (can be string "True"/"False" or boolean)
    enabled = field_value.get("enabled", False)
    if isinstance(enabled, str):
        enabled = enabled == "True"
    result["enabled"] = enabled

    # Only process sub-fields if enabled
    if enabled:
        for sub_field in field.fields:
            sub_value = field_value.get(sub_field.name)
            if sub_value is not None:
                if isinstance(sub_field, SourceFieldSelectConfig):
                    # Handle nested selects in switch groups
                    _transform_select_field(sub_field, sub_value, result)
                else:
                    # Simple sub-field
                    result[sub_field.name] = sub_value

    return result


def _transform_select_field(field: SourceFieldSelectConfig, field_value: Any, target_dict: dict[str, Any]) -> None:
    """
    Transform select field with conditional option fields.

    Frontend structure for select with option fields:
    {
        "selection": "password",
        "username": "user1",  # Option field for "password" option
        "password": "secret"  # Option field for "password" option
    }

    Backend structure:
    {
        "auth_type": "password",  # Selection promoted to main field name
        "username": "user1",     # Option fields promoted to top level
        "password": "secret"
    }
    """
    # Check if this select has option fields
    has_option_fields = any(option.fields for option in field.options if option.fields)

    if not has_option_fields:
        # Simple select - just map the value directly
        target_dict[field.name] = field_value
        return

    # Complex select with option fields
    if isinstance(field_value, dict):
        selection = field_value.get("selection")
        target_dict[field.name] = selection

        # Find the selected option and promote its fields
        selected_option = next((opt for opt in field.options if opt.value == selection), None)
        if selected_option and selected_option.fields:
            for option_field in selected_option.fields:
                option_value = field_value.get(option_field.name)
                if option_value is not None:
                    if isinstance(option_field, SourceFieldSelectConfig):
                        # Recursive handling for nested selects
                        _transform_select_field(option_field, option_value, target_dict)
                    else:
                        target_dict[option_field.name] = option_value
    else:
        # Simple value (fallback)
        target_dict[field.name] = field_value


def validate_required_fields(source_config: SourceConfig, job_inputs: dict[str, Any]) -> list[str]:
    """
    Validate that all required fields are present in job_inputs.
    Returns list of missing required field names.
    """
    missing_fields = []

    def check_field_required(field: SourceFieldConfig, data: dict[str, Any], field_path: str = "") -> None:
        full_path = f"{field_path}.{field.name}" if field_path else field.name

        if isinstance(field, SourceFieldInputConfig):
            if field.required and field.name not in data:
                missing_fields.append(full_path)

        elif isinstance(field, SourceFieldSwitchGroupConfig):
            switch_data = data.get(field.name, {})
            if isinstance(switch_data, dict) and switch_data.get("enabled"):
                for sub_field in field.fields:
                    check_field_required(sub_field, switch_data, full_path)

        elif isinstance(field, SourceFieldSelectConfig):
            if field.required and field.name not in data:
                missing_fields.append(full_path)

            # Check option fields if this select has them
            has_option_fields = any(option.fields for option in field.options if option.fields)
            if has_option_fields:
                selection = data.get(field.name)
                selected_option = next((opt for opt in field.options if opt.value == selection), None)
                if selected_option and selected_option.fields:
                    for option_field in selected_option.fields:
                        check_field_required(option_field, data, full_path)

        elif isinstance(field, SourceFieldOauthConfig):
            if field.required and field.name not in data:
                missing_fields.append(full_path)

        elif isinstance(field, SourceFieldFileUploadConfig):
            if field.required and field.name not in data:
                missing_fields.append(full_path)

    for field in source_config.fields:
        check_field_required(field, job_inputs)

    return missing_fields
