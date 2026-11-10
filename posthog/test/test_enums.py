from django.db import models
from django.db.migrations.writer import MigrationWriter
from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.enums import LabeledIntEnum, LabeledStrEnum


class QuestionType(LabeledStrEnum):
    NOUL = "noul", "Yes or no"
    CONTINUED_AS_NEW = "ContinuedAsNew"
    AI = "ai", "AI"


class QuestionTypeChoices(models.TextChoices):
    NOUL = "noul", "Yes or no"
    CONTINUED_AS_NEW = "ContinuedAsNew"
    AI = "ai", "AI"


class Level(LabeledIntEnum):
    CAN_VIEW = 21, "Can view dashboard"
    CAN_EDIT = 37


class LevelChoices(models.IntegerChoices):
    CAN_VIEW = 21, "Can view dashboard"
    CAN_EDIT = 37


class TestLabeledEnums(SimpleTestCase):
    @parameterized.expand([("str", QuestionType, QuestionTypeChoices), ("int", Level, LevelChoices)])
    def test_matches_the_django_choices_class_with_the_same_body(
        self,
        _name: str,
        labeled: type[LabeledStrEnum] | type[LabeledIntEnum],
        django_choices: type[models.TextChoices] | type[models.IntegerChoices],
    ) -> None:
        assert labeled.choices == django_choices.choices
        assert MigrationWriter.serialize(labeled.choices) == MigrationWriter.serialize(django_choices.choices)
        assert [member.label for member in labeled] == django_choices.labels

    def test_rejects_a_duplicate_value(self) -> None:
        with self.assertRaises(ValueError):

            class Broken(LabeledStrEnum):
                A = "a", "Alpha"
                B = "a", "Beta"

    def test_rejects_an_empty_choice(self) -> None:
        with self.assertRaises(TypeError):

            class Broken(LabeledStrEnum):
                __empty__ = "(none)"
                A = "a"
