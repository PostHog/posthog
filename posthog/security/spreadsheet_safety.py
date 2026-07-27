"""Defensive helpers for content destined for spreadsheet apps."""

from typing import Any

# Characters that can trigger formula execution in spreadsheet applications
_FORMULA_TRIGGER_CHARS = ("=", "+", "-", "@", "\t", "\r")


def sanitize_formula_injection(value: Any) -> Any:
    """Prefix dangerous cell values with a single quote to prevent formula injection.

    Spreadsheet applications like Excel and Google Sheets interpret cells
    starting with =, +, -, @, tab, or carriage return as formulas. Prefixing
    with a single quote forces them to be treated as plain text.
    """
    if not isinstance(value, str):
        return value
    if value and value[0] in _FORMULA_TRIGGER_CHARS:
        return f"'{value}"
    return value
