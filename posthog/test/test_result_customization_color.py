import pytest

from pydantic import TypeAdapter, ValidationError

from posthog.schema import ResultCustomizationByPosition, ResultCustomizationByValue


@pytest.mark.parametrize("token", ["preset-1", "preset-15", "preset-16", "preset-100"])
def test_result_customization_accepts_any_preset_token(token: str) -> None:
    # Custom color themes can define more than 15 colors, so the token is a
    # `preset-<n>` pattern rather than a closed enum — anything past preset-15
    # used to be rejected and made the insight unsaveable.
    assert ResultCustomizationByValue(color=token).color == token
    assert ResultCustomizationByPosition(color=token).color == token


@pytest.mark.parametrize("token", ["", "nonsense", "preset-", "preset-abc", "preset-1x"])
def test_result_customization_rejects_non_preset_token(token: str) -> None:
    with pytest.raises(ValidationError):
        ResultCustomizationByValue(color=token)


def test_result_customization_union_resolves_by_value_for_high_token() -> None:
    # `resultCustomizations` is a union of by-value and by-position dicts. A by-value
    # entry with a >15 token must resolve to the by-value variant, not fall through
    # and surface a confusing `assignmentBy` error from the by-position variant.
    adapter: TypeAdapter[dict[str, ResultCustomizationByValue] | dict[str, ResultCustomizationByPosition]] = (
        TypeAdapter(dict[str, ResultCustomizationByValue] | dict[str, ResultCustomizationByPosition])
    )
    resolved = adapter.validate_python({"k": {"assignmentBy": "value", "color": "preset-16"}})["k"]
    assert isinstance(resolved, ResultCustomizationByValue)
    assert resolved.color == "preset-16"
