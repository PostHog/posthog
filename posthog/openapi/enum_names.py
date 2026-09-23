"""Derive OpenAPI enum component names from Django Choices classes.

drf-spectacular names an enum component by hashing the field's (value, label)
pairs and looking the hash up in ENUM_NAME_OVERRIDES first. Without an
override entry the name is built from the field name and the serializer name,
so it depends on which other serializers declare a field with the same name:
a new colliding field anywhere renames an unrelated enum.

ChoicesEnumNameOverrides makes the name independent of that pool. On first
access it walks every django.db.models.Choices subclass and registers the class under a
name derived from its qualname, so the schema name follows the definition
site of the choices and never depends on the enum pool. The explicit dict
passed in wins over anything derived; it is reserved for choice sets no class
can name (see the comment on the dict in posthog/settings/web.py).

This module is imported while settings load, before Django is set up, so
everything Django- or DRF-related is imported inside the functions that run
at schema-generation time.
"""

import inspect
from collections import defaultdict
from collections.abc import ItemsView, Iterable, Iterator, KeysView, Mapping, ValuesView
from enum import Enum
from typing import Any

ENUM_SUFFIX = "Enum"


def derive_enum_name(qualname: str) -> str | None:
    """EarlyAccessFeature.Stage -> EarlyAccessFeatureStageEnum.

    A nested part that restates the outer name is collapsed, so
    Survey.SurveyType derives SurveyTypeEnum, not SurveySurveyTypeEnum.
    Returns None for names that cannot appear in a schema (locals).
    """
    name: str | None = None
    for part in qualname.split("."):
        if not part or "<" in part:
            return None
        name = part if name is None or part.startswith(name) else f"{name}{part}"
    if name is None:
        return None
    return name if name.endswith(ENUM_SUFFIX) else f"{name}{ENUM_SUFFIX}"


def build_derived_overrides(classes: Iterable[type], explicit: Mapping[str, Any]) -> dict[str, Any]:
    """Name -> Choices class for every class the explicit dict does not displace.

    Two safety rules keep the result unambiguous:
      - Classes with identical (value, label) pairs share one hash, so the
        override machinery cannot tell them apart. None of them is registered;
        the explicit dict has to name that choice set.
      - Classes that derive the same name from different choice sets are all
        skipped, because registering one would leave the others resolving to a
        component with the wrong values.
    Both cases, and a derived name colliding with a field-name based default,
    are caught loudly by posthog.openapi.enum_name_guard.
    """
    explicit_hashes = {_choices_hash(value) for value in explicit.values()}
    by_hash: dict[str, set[type]] = defaultdict(set)
    for cls in classes:
        cls_hash = _choices_hash(cls)
        if cls_hash is not None:
            by_hash[cls_hash].add(cls)

    hashes_by_name: dict[str, list[str]] = defaultdict(list)
    class_by_name: dict[str, type] = {}
    for cls_hash, class_set in by_hash.items():
        if cls_hash in explicit_hashes:
            continue
        names = {name for name in (derive_enum_name(cls.__qualname__) for cls in class_set) if name}
        if len(names) != 1:
            continue
        name = names.pop()
        if name in explicit:
            continue
        hashes_by_name[name].append(cls_hash)
        class_by_name[name] = next(iter(class_set))
    # The value registered is the class itself, so drf-spectacular applies its own
    # normalization and the hash always matches the fields built from the class.
    return {name: class_by_name[name] for name, hashes in hashes_by_name.items() if len(hashes) == 1}


def _choices_hash(value: Any) -> str | None:
    """Hash a choices value the way drf-spectacular's override loader does.

    Used only to decide which derived entries an explicit entry displaces, so
    a value that fails to normalize maps to None instead of raising.
    """
    from django.db.models import Choices  # noqa: PLC0415 because settings import this module before Django is ready

    from drf_spectacular.plumbing import (  # noqa: PLC0415 because importing DRF reads settings
        deep_import_string,
        list_hash,
    )

    try:
        if isinstance(value, str):
            value = deep_import_string(value)
        if inspect.isclass(value) and issubclass(value, Choices):
            value = value.choices
        if inspect.isclass(value) and issubclass(value, Enum):
            value = [(member.value, member.name) for member in value]
        if callable(value):
            value = value()
        normalized: list[tuple[Any, Any]] = []
        for choice in value:
            if isinstance(choice, str) or choice is None:
                normalized.append((choice, choice))
            elif isinstance(choice[1], list | tuple):
                normalized.extend(choice[1])
            else:
                normalized.append((choice[0], choice[1]))
        return list_hash([(v, label) for v, label in normalized if v not in ("", None)])
    except Exception:
        return None


def _all_subclasses(cls: type) -> Iterator[type]:
    for sub in cls.__subclasses__():
        yield sub
        yield from _all_subclasses(sub)


class ChoicesEnumNameOverrides(Mapping[str, Any]):
    """A lazy ENUM_NAME_OVERRIDES value: explicit entries over derived ones.

    The mapping is built on every read from the Choices classes imported at
    that moment. drf-spectacular reads it once per process, inside schema
    generation, after every serializer module (and with them every Choices
    class) has been imported. The result is deliberately not cached here: a
    read from a partially imported process (a test, a management command)
    must not freeze an incomplete mapping for the schema build that follows.
    """

    def __init__(self, explicit: dict[str, Any]) -> None:
        self._explicit = explicit

    def __getitem__(self, key: str) -> Any:
        return self._load()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._load())

    def __len__(self) -> int:
        return len(self._load())

    # The Mapping default views call __getitem__ once per key, which would
    # rebuild the derived mapping for every entry. One build serves the view.
    def keys(self) -> KeysView[str]:
        return self._load().keys()

    def values(self) -> ValuesView[Any]:
        return self._load().values()

    def items(self) -> ItemsView[str, Any]:
        return self._load().items()

    def _load(self) -> dict[str, Any]:
        from django.db.models import Choices  # noqa: PLC0415 because settings import this module before Django is ready

        derived = build_derived_overrides(_all_subclasses(Choices), self._explicit)
        return {**derived, **self._explicit}
