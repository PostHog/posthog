"""The config a batch export destination stores: check it against the workflow inputs.

The facade reaches this module through a call-time import, because the workflow input
dataclasses live in the service layer, which may not load on the ``django.setup()`` path.
"""

import typing
import builtins
import dataclasses
from collections.abc import Callable, Mapping

from posthog.utils import str_to_bool

from products.batch_exports.backend.facade import contracts
from products.batch_exports.backend.service import DESTINATION_WORKFLOWS, BaseBatchExportInputs


def _try_convert_to_type(value: typing.Any, target_type: type) -> tuple[typing.Any, bool]:
    """Attempt to convert value to target type based on well-known casting functions.

    This doesn't raise any exceptions but rather returns a tuple with a bool indicating
    if the value in the first position was successfully casted to `target_type` or not.
    If casting fails, the value in the first position is returned unchanged, otherwise a
    new value of type `target_type` is returned.
    """
    current_type = type(value)

    match (current_type, target_type):
        case (builtins.str, builtins.bool):
            cast_func: Callable[[typing.Any], typing.Any] = str_to_bool
        case (builtins.str, builtins.int):
            cast_func = int
        case _:
            return (value, False)

    try:
        new_value = cast_func(value)
    except Exception:
        return (value, False)

    return (new_value, True)


def validate_destination_config(
    destination_type: str, config: Mapping[str, typing.Any], *, partial: bool
) -> dict[str, typing.Any]:
    """Check a destination config against the workflow inputs of its destination type.

    Ensure that the config passes the following checks:
    * Does NOT contain fields that do not exist in workflow inputs.
    * Contains all required fields as defined by workflow inputs, unless ``partial``.
    * Provided values match types required by workflow inputs.

    Returns a copy of the config with values converted to the declared types.

    Raises:
        A `contracts.InvalidDestinationConfigError` if any of these checks fail.
    """
    validated = dict(config)

    _, workflow_inputs = DESTINATION_WORKFLOWS[destination_type]
    base_field_names = {field.name for field in dataclasses.fields(BaseBatchExportInputs)}
    workflow_fields = dataclasses.fields(workflow_inputs)
    destination_fields = {field for field in workflow_fields if field.name not in base_field_names}

    extra_fields = validated.keys() - {field.name for field in destination_fields} - base_field_names
    if extra_fields:
        str_fields = ", ".join(f"'{extra_field}'" for extra_field in sorted(extra_fields))
        raise contracts.InvalidDestinationConfigError(f"Configuration has unknown field/s: {str_fields}")

    # Destination config fields without a dataclass default must be provided.
    for destination_field in destination_fields:
        is_required = (
            destination_field.default == dataclasses.MISSING
            and destination_field.default_factory == dataclasses.MISSING
        )
        if destination_field.name not in validated:
            if is_required and not partial:
                # When patching we expect a partial configuration. So, we don't
                # error on missing required fields.
                raise contracts.InvalidDestinationConfigError(
                    f"Configuration missing required field: '{destination_field.name}'"
                )
            else:
                continue

        config_value = validated[destination_field.name]
        field_type = destination_field.type

        if not isinstance(field_type, type):
            # `dataclasses.Field.type` could be something we can't work with.
            # TODO: Validate these ones too?
            continue

        if not isinstance(config_value, field_type):
            config_value, success = _try_convert_to_type(config_value, field_type)

            if not success:
                raise contracts.InvalidDestinationConfigError(
                    f"Configuration has invalid type: got '{type(config_value).__name__}', expected '{field_type.__name__}'"
                )

            validated[destination_field.name] = config_value

    return validated
