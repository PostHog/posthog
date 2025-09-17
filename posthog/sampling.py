import structlog

logger = structlog.get_logger(__name__)


def clamp_to_range(
    value, min_val: float, max_val: float, label: str | None = None, fallback_value: float | None = None
) -> float:
    """
    Clamps a value to a range. This has been ported from posthog-js.
    https://github.com/PostHog/posthog-js/blob/9de949e26c560535122c50d7fcf9e74d4361ecef/src/utils/number-utils.ts#L4-L33

    Args:
        value: The value to clamp
        min_val: The minimum value
        max_val: The maximum value
        label: If provided, enables logging and prefixes all logs with the label
        fallback_value: If provided, returns this value if the value is not a valid number

    Returns:
        The clamped value
    """
    if min_val > max_val:
        if label:
            logger.warning(f"{label}: min cannot be greater than max")
        min_val = max_val

    try:
        if not isinstance(value, int | float):
            if label:
                logger.warning(
                    f"{label} must be a number. Using max or fallback. max: {max_val}, fallback: {fallback_value}"
                )
            value = float(fallback_value if fallback_value is not None else max_val)
    except (TypeError, ValueError):
        value = float(fallback_value if fallback_value is not None else max_val)

    # Now clamp the value
    if value > max_val:
        if label:
            logger.warning(f"{label} cannot be greater than max: {max_val}. Using max value instead.")
        return max_val
    elif value < min_val:
        if label:
            logger.warning(f"{label} cannot be less than min: {min_val}. Using min value instead.")
        return min_val
    else:
        return float(value)


def simple_hash(s: str | None) -> int:
    hash_val = 0
    if s is None:
        return hash_val
    for char in s:
        # we could probably use a 64bit in the backend but let's keep it as posthog-js
        hash_val = (hash_val * 31 + ord(char)) & 0xFFFFFFFF  # 32-bit unsigned
    return hash_val


# This is the same as posthog-js, prop here is any string value that we want to sample on
def sample_on_property(prop: str, percent: float) -> bool:
    """
    Uses the hash function to determine whether a property should be included
    in the sample based on a percentage.

    Args:
        prop: The string property to sample on
        percent: A number between 0 and 1 representing the sampling rate

    Returns:
        bool: True if the property should be included in the sample
    """
    if not prop:
        return True

    percent = clamp_to_range(percent, 0, 1, "Sampling rate")
    return simple_hash(prop) % 100 < int(percent * 100)
