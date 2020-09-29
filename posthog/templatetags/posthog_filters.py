import math
from typing import Optional, Union

from django import template

register = template.Library()

Number = Union[int, float]


@register.filter
def compact_number(value: Number, max_decimals: int = 1) -> str:
    """
    Returns a number in a compact format with a thousands or millions suffix if applicable.
    Example:
      {% compact_number 5500000 %}
      =>  "5.5M"
    """

    def suffix_formatted(value: Number, base: float, suffix: str) -> str:
        multiplier: int = 10 ** max_decimals
        return f"{str(math.floor(value * multiplier / base) / multiplier).rstrip('0').rstrip('.')}{suffix}"

    if value < 1000:
        return str(math.floor(value))

    if value < 1_000_000:
        return suffix_formatted(value, 1_000.0, "K")

    if value < 1_000_000_000:
        return suffix_formatted(value, 1_000_000.0, "M")

    return suffix_formatted(value, 1_000_000_000.0, "B")


@register.filter
def percentage(value: Optional[Number], decimals: int = 1) -> str:
    """
    Returns a rounded formatted with a specific number of decimal digits and a % sign. Expects a decimal-based ratio.
    Example:
      {% percentage 0.2283113 %}
      =>  "22.8%"
    """

    if value is None:
        return "-"

    return "{0:.{decimals}f}%".format(value * 100, decimals=decimals)
