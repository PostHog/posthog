from posthog.test.base import BaseTest

from django.db import IntegrityError, transaction

from parameterized import parameterized

from products.customer_analytics.backend.models import CustomPropertyDefinition


class TestCustomPropertyDefinitionConstraints(BaseTest):
    # The facade coerces is_big_number to false for non-numeric types; these assert the DB CHECK
    # constraint holds the same invariant for writers that bypass the facade (direct ORM, admin).
    @parameterized.expand(["text", "date", "datetime", "boolean"])
    def test_big_number_rejected_for_non_numeric_display_type(self, display_type):
        with self.assertRaises(IntegrityError), transaction.atomic():
            # nosemgrep: idor-lookup-without-team (test exercises the DB constraint directly)
            CustomPropertyDefinition.objects.unscoped().create(
                team=self.team, name=f"bad-{display_type}", display_type=display_type, is_big_number=True
            )

    @parameterized.expand(["number", "currency", "percent"])
    def test_big_number_allowed_for_numeric_display_type(self, display_type):
        # nosemgrep: idor-lookup-without-team (test exercises the DB constraint directly)
        definition = CustomPropertyDefinition.objects.unscoped().create(
            team=self.team, name=f"ok-{display_type}", display_type=display_type, is_big_number=True
        )
        self.assertTrue(definition.is_big_number)
