"""Normalize a hog function's config for comparison by dropping the values validation derives from it."""

from typing import Any


def _without(value: Any, keys: tuple[str, ...]) -> Any:
    return {k: v for k, v in value.items() if k not in keys} if isinstance(value, dict) else value


def _inputs_without_derived(inputs: Any) -> Any:
    if not isinstance(inputs, dict):
        return inputs
    return {
        key: _without(value, ("bytecode", "bytecode_contract", "transpiled", "order")) for key, value in inputs.items()
    }


def comparable_content(content: dict) -> dict:
    """A config snapshot with the values validation derives from it dropped: filter and input
    bytecode, the runtime stamp beside it, transpiled JS, input ordering.

    A background re-save can change those on its own without the config changing at all — most often
    `refresh_affected_hog_functions` recompiling filter bytecode after an action or cohort edit — so
    comparing them would version a plain rename.
    """
    filter_derived = ("bytecode", "bytecode_error", "bytecode_contract", "transpiled")
    mappings = content.get("mappings")
    return {
        **content,
        "filters": _without(content.get("filters"), filter_derived),
        "inputs": _inputs_without_derived(content.get("inputs")),
        "masking": _without(content.get("masking"), ("bytecode",)),
        "mappings": [
            {
                **mapping,
                "filters": _without(mapping.get("filters"), filter_derived),
                "inputs": _inputs_without_derived(mapping.get("inputs")),
            }
            if isinstance(mapping, dict)
            else mapping
            for mapping in mappings
        ]
        if isinstance(mappings, list)
        else mappings,
    }
