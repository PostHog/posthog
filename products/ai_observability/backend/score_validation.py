import math
from decimal import Decimal, InvalidOperation
from fractions import Fraction


def _decimal_from_config(value: object) -> Decimal | None:
    if value is None:
        return None

    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _int_from_config(value: object) -> int | None:
    if not isinstance(value, str | int | float):
        return None

    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _is_float_on_step(value: float, base: Decimal, step: Decimal) -> bool:
    # Fractions avoid overflow when a finite binary64 value is divided by a very small step.
    remainder = (Fraction(Decimal(str(value))) - Fraction(base)) % Fraction(step)
    distance = min(remainder, Fraction(step) - remainder)
    # Allow SDK arithmetic such as 0.1 + 0.2 without letting large values skip step validation.
    tolerance = Fraction(step) / 1_000_000
    return distance <= tolerance


def _is_float_at_boundary(value: float, boundary: Decimal, step: Decimal | None) -> bool:
    # Zero has no relative scale, but SDK subtraction can leave a small residue.
    scale = abs(Fraction(boundary)) if boundary else Fraction(1)
    ulp = math.ulp(value) if boundary else math.ulp(1.0)
    # The caps keep large and subnormal floats from meaningfully extending the range.
    tolerance = min(Fraction(ulp) * 4, scale / 1_000_000_000_000, Fraction(1, 1_000_000_000_000))
    if step is not None:
        tolerance = min(tolerance, Fraction(step) / 1_000_000)
    return abs(Fraction(Decimal(str(value))) - Fraction(boundary)) <= tolerance


def _validate_categorical_score(config: dict[str, object], categorical_values: list[str] | None) -> dict[str, str]:
    if categorical_values is None:
        return {"categorical_values": "This scorer requires `categorical_values`."}

    configured_options = config.get("options", [])
    options = configured_options if isinstance(configured_options, list) else []
    option_keys = {
        option["key"] for option in options if isinstance(option, dict) and isinstance(option.get("key"), str)
    }
    if any(option_key not in option_keys for option_key in categorical_values):
        return {"categorical_values": "Select valid categorical option keys."}

    selection_mode = config.get("selection_mode") or "single"
    selection_count = len(categorical_values)

    if selection_mode == "single":
        if selection_count != 1:
            return {"categorical_values": "This scorer allows exactly one categorical option."}
        return {}

    minimum = _int_from_config(config.get("min_selections"))
    maximum = _int_from_config(config.get("max_selections"))

    if minimum is not None and selection_count < minimum:
        return {"categorical_values": f"Select at least {minimum} categorical options."}

    if maximum is not None and selection_count > maximum:
        return {"categorical_values": f"Select no more than {maximum} categorical options."}

    return {}


def _validate_numeric_score(config: dict[str, object], numeric_value: Decimal | float | None) -> dict[str, str]:
    if numeric_value is None:
        return {"numeric_value": "This scorer requires `numeric_value`."}

    if not math.isfinite(numeric_value):
        return {"numeric_value": "Provide a finite numeric value."}

    numeric_minimum = _decimal_from_config(config.get("min"))
    numeric_maximum = _decimal_from_config(config.get("max"))
    numeric_step = _decimal_from_config(config.get("step"))

    if any(value is not None and not value.is_finite() for value in (numeric_minimum, numeric_maximum, numeric_step)):
        return {"numeric_value": "This scorer has an invalid numeric configuration."}
    if numeric_step is not None and numeric_step <= 0:
        return {"numeric_value": "This scorer has an invalid numeric configuration."}

    decimal_value = Decimal(str(numeric_value)) if isinstance(numeric_value, float) else numeric_value
    if (
        numeric_minimum is not None
        and decimal_value < numeric_minimum
        and not (
            isinstance(numeric_value, float) and _is_float_at_boundary(numeric_value, numeric_minimum, numeric_step)
        )
    ):
        return {"numeric_value": f"Ensure this value is greater than or equal to {numeric_minimum}."}

    if (
        numeric_maximum is not None
        and decimal_value > numeric_maximum
        and not (
            isinstance(numeric_value, float) and _is_float_at_boundary(numeric_value, numeric_maximum, numeric_step)
        )
    ):
        return {"numeric_value": f"Ensure this value is less than or equal to {numeric_maximum}."}

    if numeric_step is not None:
        base = numeric_minimum if numeric_minimum is not None else Decimal("0")
        on_step = (
            _is_float_on_step(numeric_value, base, numeric_step)
            if isinstance(numeric_value, float)
            else (Fraction(numeric_value) - Fraction(base)) % Fraction(numeric_step) == 0
        )
        if not on_step:
            return {"numeric_value": f"Ensure this value increments by {numeric_step}."}

    return {}


def validate_score_value(
    kind: str,
    config: dict[str, object],
    *,
    numeric_value: Decimal | float | None = None,
    boolean_value: bool | None = None,
    categorical_values: list[str] | None = None,
) -> dict[str, str]:
    if kind == "categorical":
        return _validate_categorical_score(config, categorical_values)
    if kind == "numeric":
        return _validate_numeric_score(config, numeric_value)
    if boolean_value is None:
        return {"boolean_value": "This scorer requires `boolean_value`."}
    return {}
