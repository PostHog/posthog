"""Unit tests for `body_factory.build_minimal_post_body`.

Pure tests — no DB needed. Production-shape Django models are referenced
to keep introspection realistic, but no model instances are created.
"""

from __future__ import annotations

import pytest

from rest_framework import serializers

from posthog.models.cohort import Cohort
from posthog.models.insight import Insight
from posthog.test.idor.body_factory import BodyUnfillable, build_minimal_post_body


class _SimpleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Insight
        fields = ["id", "name"]


class _RequiredCharSerializer(serializers.Serializer):
    name = serializers.CharField(required=True, max_length=64)


class _OptionalNotSynthesizedSerializer(serializers.Serializer):
    """Optional fields aren't included in the body — only required ones."""

    name = serializers.CharField(required=False)
    description = serializers.CharField(required=False)


class _ChoiceSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=["admin", "user"], required=True)


class _ChoiceNoChoicesSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=[], required=True)


class _IntegerSerializer(serializers.Serializer):
    count = serializers.IntegerField(required=True)


class _BooleanSerializer(serializers.Serializer):
    active = serializers.BooleanField(required=True)


class _DateSerializer(serializers.Serializer):
    when = serializers.DateField(required=True)
    when_dt = serializers.DateTimeField(required=True)


class _JSONSerializer(serializers.Serializer):
    config = serializers.JSONField(required=True)


class _ManyRelatedSerializer(serializers.Serializer):
    things = serializers.PrimaryKeyRelatedField(many=True, queryset=Cohort.objects.all(), required=True)


class _NoRequiredFieldsSerializer(serializers.ModelSerializer):
    class Meta:
        model = Insight
        fields = ["id"]


class _UnsupportedFieldSerializer(serializers.Serializer):
    blob = serializers.FileField(required=True)


@pytest.fixture()
def fake_team() -> object:
    """A stand-in Team — body_factory accesses .pk for context but doesn't touch DB."""

    class _Team:
        pk = 0
        id = 0

    return _Team()


class TestBuildMinimalPostBody:
    def test_required_charfield_is_synthesized(self, fake_team: object) -> None:
        body = build_minimal_post_body(_RequiredCharSerializer, team=fake_team)  # type: ignore[arg-type]
        assert "name" in body
        assert isinstance(body["name"], str)
        assert len(body["name"]) <= 64

    def test_optional_fields_are_omitted(self, fake_team: object) -> None:
        body = build_minimal_post_body(_OptionalNotSynthesizedSerializer, team=fake_team)  # type: ignore[arg-type]
        assert body == {}

    def test_choice_field_picks_first_choice(self, fake_team: object) -> None:
        body = build_minimal_post_body(_ChoiceSerializer, team=fake_team)  # type: ignore[arg-type]
        assert body == {"role": "admin"}

    def test_empty_choice_field_raises(self, fake_team: object) -> None:
        with pytest.raises(BodyUnfillable):
            build_minimal_post_body(_ChoiceNoChoicesSerializer, team=fake_team)  # type: ignore[arg-type]

    def test_integer_default_is_zero(self, fake_team: object) -> None:
        body = build_minimal_post_body(_IntegerSerializer, team=fake_team)  # type: ignore[arg-type]
        assert body == {"count": 0}

    def test_boolean_default_is_false(self, fake_team: object) -> None:
        body = build_minimal_post_body(_BooleanSerializer, team=fake_team)  # type: ignore[arg-type]
        assert body == {"active": False}

    def test_date_and_datetime_iso(self, fake_team: object) -> None:
        body = build_minimal_post_body(_DateSerializer, team=fake_team)  # type: ignore[arg-type]
        assert isinstance(body["when"], str)
        assert isinstance(body["when_dt"], str)
        # ISO-format dates contain a "-"; minimal sanity check.
        assert "-" in body["when"]

    def test_json_default_is_empty_dict(self, fake_team: object) -> None:
        body = build_minimal_post_body(_JSONSerializer, team=fake_team)  # type: ignore[arg-type]
        assert body == {"config": {}}

    def test_many_related_default_is_empty_list(self, fake_team: object) -> None:
        body = build_minimal_post_body(_ManyRelatedSerializer, team=fake_team)  # type: ignore[arg-type]
        assert body == {"things": []}

    def test_no_required_fields_returns_empty(self, fake_team: object) -> None:
        body = build_minimal_post_body(_NoRequiredFieldsSerializer, team=fake_team)  # type: ignore[arg-type]
        assert body == {}

    def test_unsupported_field_type_raises(self, fake_team: object) -> None:
        with pytest.raises(BodyUnfillable):
            build_minimal_post_body(_UnsupportedFieldSerializer, team=fake_team)  # type: ignore[arg-type]


class TestRegistryOverride:
    def test_registered_factory_takes_precedence(self, fake_team: object) -> None:
        from posthog.test.idor.post_body_fixtures import register_post_body

        sentinel_body = {"forced": True}

        def _factory(_team: object) -> dict:
            return sentinel_body

        register_post_body(_RequiredCharSerializer, _factory)  # type: ignore[arg-type]
        try:
            body = build_minimal_post_body(_RequiredCharSerializer, team=fake_team)  # type: ignore[arg-type]
            assert body == sentinel_body
        finally:
            from posthog.test.idor.post_body_fixtures import _REGISTRY

            _REGISTRY.pop(_RequiredCharSerializer, None)
