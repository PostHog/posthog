# Test cases for choices-need-a-class.
# ruff: noqa
import typing
from typing import Literal, get_args

from django.db import models

from rest_framework import fields, serializers
from rest_framework.fields import ChoiceField

from posthog.enums import LabeledStrEnum

ConflictCode = Literal["dataset_archived", "stale_version"]


class Stage(models.TextChoices):
    DRAFT = "draft"
    LIVE = "live"


class PinKind(LabeledStrEnum):
    PINNED = "pinned"


class ExampleSerializer(serializers.Serializer):
    # ruleid: choices-need-a-class
    code = serializers.ChoiceField(choices=["dataset_archived", "stale_version"])

    # ruleid: choices-need-a-class
    status = serializers.ChoiceField(["active", "resolved"], required=False)

    # ruleid: choices-need-a-class
    tags = serializers.MultipleChoiceField(choices=[("a", "A"), ("b", "B")])

    # ruleid: choices-need-a-class
    level = serializers.ChoiceField(choices=[stage.value for stage in Stage])

    # ruleid: choices-need-a-class
    reason = serializers.ChoiceField(choices=get_args(ConflictCode))

    # ruleid: choices-need-a-class
    other_reason = serializers.ChoiceField(choices=typing.get_args(ConflictCode))

    # ruleid: choices-need-a-class
    kind = ChoiceField(choices=["freeform", "grid"])

    # ruleid: choices-need-a-class
    mode = fields.ChoiceField(choices=["fast", "slow"])

    # ruleid: choices-need-a-class
    sources = serializers.ListField(child=serializers.ChoiceField(choices=["manual", "agent"]))

    # ok: choices-need-a-class
    stage = serializers.ChoiceField(choices=Stage.choices)

    # ok: choices-need-a-class
    pin_kind = serializers.ChoiceField(choices=PinKind.choices)

    # ok: choices-need-a-class
    exempt = serializers.ChoiceField(choices=["x", "y"])  # nosemgrep: choices-need-a-class -- test exemption


class ExampleModel(models.Model):
    # ruleid: choices-need-a-class
    cadence = models.CharField(max_length=10, choices=[("daily", "Daily"), ("weekly", "Weekly")])

    # ok: choices-need-a-class
    stage = models.CharField(max_length=10, choices=Stage.choices)

    # ok: choices-need-a-class
    name = models.CharField(max_length=10)
