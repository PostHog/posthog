"""
JSON-FK runtime probes.

Discovery cannot inspect inside `JSONField` / `DictField` properties, so
tenant-scoped FK ids smuggled into JSON (Cohort filters, FeatureFlag
filters, Insight queries, HogFlow trees, Alert configs) are invisible
to the parametric sweep.

This module provides a registry of per-shape probe functions. Each
probe takes a synthesized request body and a victim's pk, and returns
a mutated body with the victim's id smuggled into the JSON field at
the right depth. The runtime parametric in `test_idor_coverage.py`
iterates the registry, builds the body via `build_minimal_post_body`,
runs each probe, and PATCHes the attacker's own resource with the
mutated body. A vulnerable handler accepts the cross-tenant id without
re-validating it against the caller's tenant.

Adding a new probe is two lines plus the inject function:

    register_json_probe(
        serializer_class=CohortSerializer,
        field_name="filters",
        inject_fn=_cohort_filters_inject_cohort_id,
        target_model=Cohort,
        description="Cohort filters can carry nested cohort_id refs in property values.",
    )

The inject function receives `(body, victim_pk)` and is expected to
return a fully-formed body dict. It is responsible for ensuring the
JSON field exists on the body and for injecting the victim's pk at
the depth the serializer's validate() / save() would dereference.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from django.db import models

from rest_framework import serializers


@dataclass(frozen=True)
class JsonFkProbe:
    """A probe that injects a tenant-scoped victim pk into a JSON field of a serializer."""

    serializer_class: type[serializers.Serializer]
    """The serializer that exposes the JSON field."""

    field_name: str
    """Name of the JSON/Dict field on the serializer."""

    inject_fn: Callable[[dict[str, Any], Any], dict[str, Any]]
    """Mutator that smuggles the victim's pk into `body[field_name]`."""

    target_model: type[models.Model]
    """The Django model class the injected value points at."""

    description: str = ""
    """Free-form note for the punch list / failure message."""


_PROBES: list[JsonFkProbe] = []


def register_json_probe(
    serializer_class: type[serializers.Serializer],
    field_name: str,
    inject_fn: Callable[[dict[str, Any], Any], dict[str, Any]],
    target_model: type[models.Model],
    *,
    description: str = "",
) -> None:
    """Register a probe. Idempotent on (serializer_class, field_name, target_model)."""
    record = JsonFkProbe(
        serializer_class=serializer_class,
        field_name=field_name,
        inject_fn=inject_fn,
        target_model=target_model,
        description=description,
    )
    for existing in _PROBES:
        if (
            existing.serializer_class is record.serializer_class
            and existing.field_name == record.field_name
            and existing.target_model is record.target_model
        ):
            return
    _PROBES.append(record)


def get_registered_probes() -> list[JsonFkProbe]:
    """Return a copy of the registered probes (the registry is module-global)."""
    return list(_PROBES)


def _reset_for_tests() -> None:
    """Test-only helper to reset the registry between unit tests."""
    _PROBES.clear()


# ---------------------------------------------------------------------------
# Built-in probes
#
# Probes live alongside the registry rather than in a separate file so the
# import side-effect that registers them is co-located. Adding a probe means
# editing this file in two places: the inject function + the register call.
# ---------------------------------------------------------------------------


def _cohort_filters_inject_cohort_id(body: dict[str, Any], victim_pk: Any) -> dict[str, Any]:
    """Smuggle a victim cohort_id into the `filters.properties[].value` slot.

    Cohort.filters has shape:
        {"properties": {"type": "AND", "values": [{"type": "person", "values": [...]}]}}
    Property entries with `type: "cohort"` reference a cohort by pk in `value`.
    """
    body["filters"] = {
        "properties": {
            "type": "AND",
            "values": [
                {
                    "type": "AND",
                    "values": [{"key": "id", "type": "cohort", "value": victim_pk}],
                }
            ],
        }
    }
    return body


def _feature_flag_filters_inject_cohort_id(body: dict[str, Any], victim_pk: Any) -> dict[str, Any]:
    """Smuggle a victim cohort_id into a FeatureFlag rollout group's cohort property.

    FeatureFlag.filters has shape:
        {"groups": [{"properties": [{"key": "id", "type": "cohort", "value": <cohort_id>}],
                     "rollout_percentage": 100}]}
    """
    body["filters"] = {
        "groups": [
            {
                "properties": [{"key": "id", "type": "cohort", "value": victim_pk}],
                "rollout_percentage": 100,
            }
        ]
    }
    return body


def _register_builtin_probes() -> None:
    """Register the curated set of high-value JSON-FK probes.

    Imports happen here so this module stays importable when the registry
    is consumed without Django app loading (e.g., type-only tooling).
    """
    from posthog.api.cohort import CohortSerializer
    from posthog.api.feature_flag import FeatureFlagSerializer
    from posthog.models.cohort import Cohort

    register_json_probe(
        serializer_class=CohortSerializer,
        field_name="filters",
        inject_fn=_cohort_filters_inject_cohort_id,
        target_model=Cohort,
        description="Cohort.filters can carry nested cohort_id refs in property values.",
    )
    register_json_probe(
        serializer_class=FeatureFlagSerializer,
        field_name="filters",
        inject_fn=_feature_flag_filters_inject_cohort_id,
        target_model=Cohort,
        description="FeatureFlag.filters rollout groups can reference a cohort by pk.",
    )


_register_builtin_probes()
