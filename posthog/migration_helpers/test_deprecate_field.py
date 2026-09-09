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


def test_a_non_nullable_field_is_refused() -> None:
    with pytest.raises(FieldDeprecatedError, match="null=True"):
        deprecate_field(models.CharField(max_length=8, null=False))
