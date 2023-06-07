import pytest

from ee.models.property_definition import EnterprisePropertyDefinition
from posthog.test.base import BaseTest


class TestPropertyDefinition(BaseTest):
    def test_errors_on_invalid_verified_by_type(self):
        with pytest.raises(ValueError):
            EnterprisePropertyDefinition.objects.create(
                team=self.team, name="enterprise property", owner=self.user, verified_by="Not user id"  # type: ignore
            )

    def test_default_verified_false(self):
        definition = EnterprisePropertyDefinition.objects.create(
            team=self.team, name="enterprise property", owner=self.user
        )
        assert definition.verified is False
