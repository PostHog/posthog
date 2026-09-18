"""Tests for the deprecate_field helper.

The helper decides what to return from sys.argv, because a model class body runs at import
time, before anything else can say what this process is about to do. That coupling is easy
to break by accident, so both directions are pinned here.
"""

import sys

import pytest
from unittest.mock import patch

from django.db import models

from parameterized import parameterized

from posthog.migration_helpers.deprecate_field import DeprecatedField, FieldDeprecatedError, deprecate_field
from posthog.models.personal_api_key import PersonalAPIKey


@parameterized.expand([("makemigrations",), ("analyze_migration_risk",)])
def test_migration_commands_get_the_real_field(command: str) -> None:
    with patch.object(sys, "argv", ["manage.py", command]):
        field: models.CharField = models.CharField(max_length=8, null=True)

        assert deprecate_field(field) is field


@parameterized.expand([("runserver",), ("shell",)])
def test_other_commands_get_a_descriptor(command: str) -> None:
    with patch.object(sys, "argv", ["manage.py", command]):
        assert isinstance(deprecate_field(models.CharField(max_length=8, null=True)), DeprecatedField)


def test_a_migration_command_in_a_later_argument_does_not_count() -> None:
    with patch.object(sys, "argv", ["pytest", "-k", "migrate"]):
        assert isinstance(deprecate_field(models.CharField(max_length=8, null=True)), DeprecatedField)


@parameterized.expand(
    [
        ("foreign_key", models.ForeignKey("posthog.Team", null=True, on_delete=models.CASCADE)),
        ("one_to_one", models.OneToOneField("posthog.Team", null=True, on_delete=models.CASCADE)),
        ("many_to_many", models.ManyToManyField("posthog.Team")),
    ]
)
def test_a_relation_is_refused(_name: str, field: models.Field) -> None:
    with pytest.raises(FieldDeprecatedError, match="untrack_field"):
        deprecate_field(field)


def test_a_non_nullable_field_is_refused() -> None:
    with pytest.raises(FieldDeprecatedError, match="null=True"):
        deprecate_field(models.CharField(max_length=8, null=False))


class _Holder:
    field = DeprecatedField()


class _StrictHolder:
    field = DeprecatedField(raise_on_access=True)


def test_a_read_returns_none() -> None:
    with pytest.warns(DeprecationWarning, match="_Holder.field"):
        assert _Holder().field is None


def test_a_write_is_dropped() -> None:
    holder = _Holder()

    with pytest.warns(DeprecationWarning, match="writing to deprecated field"):
        holder.field = "kept nowhere"

    with pytest.warns(DeprecationWarning):
        assert holder.field is None


def test_raise_on_access_raises_instead_of_warning() -> None:
    with pytest.raises(FieldDeprecatedError, match="_StrictHolder.field"):
        _ = _StrictHolder().field


def test_a_model_field_reports_its_own_name() -> None:
    with pytest.warns(DeprecationWarning, match="PersonalAPIKey.value"):
        assert PersonalAPIKey().value is None
