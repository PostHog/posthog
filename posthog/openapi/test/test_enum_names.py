from django.db import models
from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.openapi.enum_names import build_derived_overrides, derive_enum_name


class Fruit(models.TextChoices):
    APPLE = "apple", "Apple"
    PEAR = "pear", "Pear"


class FruitCopy(models.TextChoices):
    APPLE = "apple", "Apple"
    PEAR = "pear", "Pear"


class Basket(models.TextChoices):
    SMALL = "small", "Small"
    LARGE = "large", "Large"


class TestDeriveEnumName(SimpleTestCase):
    @parameterized.expand(
        [
            ("plain class", "Fruit", "FruitEnum"),
            ("nested class", "EarlyAccessFeature.Stage", "EarlyAccessFeatureStageEnum"),
            ("repeated prefix collapses", "Survey.SurveyType", "SurveyTypeEnum"),
            ("existing suffix kept", "Basket.BasketEnum", "BasketEnum"),
            ("locals rejected", "make_choices.<locals>.Fruit", None),
        ]
    )
    def test_derives(self, _name: str, qualname: str, expected: str | None) -> None:
        assert derive_enum_name(qualname) == expected


class TestBuildDerivedOverrides(SimpleTestCase):
    def test_registers_class_under_derived_name(self) -> None:
        overrides = build_derived_overrides([Fruit, Basket], {})
        assert overrides == {"FruitEnum": Fruit, "BasketEnum": Basket}

    def test_identical_choice_sets_are_left_to_the_explicit_dict(self) -> None:
        overrides = build_derived_overrides([Fruit, FruitCopy, Basket], {})
        assert overrides == {"BasketEnum": Basket}

    def test_explicit_entry_displaces_derived_by_name_and_by_hash(self) -> None:
        explicit = {"FruitEnum": ["kiwi"], "ProduceEnum": [["apple", "Apple"], ["pear", "Pear"]]}
        overrides = build_derived_overrides([Fruit, Basket], explicit)
        # FruitEnum is taken by name, and Fruit's own pairs are taken by hash
        # through ProduceEnum, so only Basket survives.
        assert overrides == {"BasketEnum": Basket}
