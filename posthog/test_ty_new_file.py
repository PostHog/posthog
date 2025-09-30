"""Test file to simulate new code from non-ty user."""


def broken_function() -> str:
    x: str = 123  # Type error
    return x


def my_new_code() -> int:
    """Ty user adds new function."""
    return 42
