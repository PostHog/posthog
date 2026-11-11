from django.test import SimpleTestCase

from posthog.models.property.property import SEMVER_OPERATORS, SemverOperator
from posthog.schema_enums import PropertyOperator


class TestSemverOperators(SimpleTestCase):
    def test_semver_operators_match_the_generated_operator_enum(self) -> None:
        generated = {op.value for op in PropertyOperator if op.value.startswith("semver_")}

        self.assertEqual(set(SemverOperator.values), generated)
        self.assertEqual(set(SEMVER_OPERATORS), generated)
