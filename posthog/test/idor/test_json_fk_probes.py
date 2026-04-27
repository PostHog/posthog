"""Unit tests for `json_fk_probes` registry mechanism."""

from __future__ import annotations

from rest_framework import serializers

from posthog.models.cohort import Cohort
from posthog.test.idor.json_fk_probes import JsonFkProbe, _reset_for_tests, get_registered_probes, register_json_probe


class _FakeSerializer(serializers.Serializer):
    pass


def _noop_inject(body, victim_pk):
    body["filters"] = {"victim_pk": victim_pk}
    return body


class TestJsonFkProbeRegistry:
    def setup_method(self) -> None:
        _reset_for_tests()

    def test_register_appends_record(self) -> None:
        register_json_probe(
            serializer_class=_FakeSerializer,
            field_name="filters",
            inject_fn=_noop_inject,
            target_model=Cohort,
        )
        probes = get_registered_probes()
        assert len(probes) == 1
        assert probes[0].serializer_class is _FakeSerializer
        assert probes[0].field_name == "filters"
        assert probes[0].target_model is Cohort

    def test_register_idempotent_on_same_tuple(self) -> None:
        register_json_probe(_FakeSerializer, "filters", _noop_inject, Cohort)
        register_json_probe(_FakeSerializer, "filters", _noop_inject, Cohort)
        assert len(get_registered_probes()) == 1

    def test_inject_fn_invocation(self) -> None:
        register_json_probe(_FakeSerializer, "filters", _noop_inject, Cohort)
        probe = get_registered_probes()[0]
        body = probe.inject_fn({}, victim_pk=42)
        assert body == {"filters": {"victim_pk": 42}}

    def test_get_registered_probes_returns_copy(self) -> None:
        register_json_probe(_FakeSerializer, "filters", _noop_inject, Cohort)
        first = get_registered_probes()
        first.append(JsonFkProbe(_FakeSerializer, "other", _noop_inject, Cohort))
        # Module registry must remain length 1 — get_registered_probes returns a copy.
        assert len(get_registered_probes()) == 1

    def test_jsonfkprobe_carries_description(self) -> None:
        register_json_probe(
            serializer_class=_FakeSerializer,
            field_name="filters",
            inject_fn=_noop_inject,
            target_model=Cohort,
            description="probe description",
        )
        assert get_registered_probes()[0].description == "probe description"


class TestBuiltinProbes:
    def test_builtins_registered_at_import(self) -> None:
        # Re-import to trigger _register_builtin_probes after a teardown elsewhere.
        from posthog.test.idor.json_fk_probes import _register_builtin_probes, get_registered_probes

        _reset_for_tests()
        _register_builtin_probes()
        probes = get_registered_probes()
        names = {(p.serializer_class.__name__, p.field_name) for p in probes}
        assert ("CohortSerializer", "filters") in names
        assert ("FeatureFlagSerializer", "filters") in names

    def test_cohort_filters_inject_shape(self) -> None:
        from posthog.test.idor.json_fk_probes import _cohort_filters_inject_cohort_id

        body = _cohort_filters_inject_cohort_id({}, victim_pk=99)
        # Walk into the nested shape and assert the victim pk lands in `value`.
        prop = body["filters"]["properties"]["values"][0]["values"][0]
        assert prop["type"] == "cohort"
        assert prop["value"] == 99

    def test_feature_flag_filters_inject_shape(self) -> None:
        from posthog.test.idor.json_fk_probes import _feature_flag_filters_inject_cohort_id

        body = _feature_flag_filters_inject_cohort_id({}, victim_pk=42)
        prop = body["filters"]["groups"][0]["properties"][0]
        assert prop["type"] == "cohort"
        assert prop["value"] == 42
        assert body["filters"]["groups"][0]["rollout_percentage"] == 100
