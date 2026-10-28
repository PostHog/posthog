import pytest
from posthog.test.base import BaseTest

from django.utils import timezone

from products.event_definitions.backend.models.enterprise_copies import PROPERTY_DEFINITION_COPIES
from products.event_definitions.backend.models.property_definition import PropertyDefinition

from ee.models.property_definition import EnterprisePropertyDefinition


class TestPropertyDefinition(BaseTest):
    def test_errors_on_invalid_verified_by_type(self):
        with pytest.raises(ValueError):
            EnterprisePropertyDefinition.objects.create(
                team=self.team,
                name="enterprise property",
                verified_by="Not user id",  # type: ignore
            )

    def test_default_verified_false(self):
        definition = EnterprisePropertyDefinition.objects.create(team=self.team, name="enterprise property")
        assert definition.verified is False

    def test_save_keeps_base_copies_equal_to_enterprise_fields(self):
        definition = EnterprisePropertyDefinition.objects.create(
            team=self.team,
            name="enterprise definition",
            description="first",
            updated_by=self.user,
            verified=True,
            verified_by=self.user,
            verified_at=timezone.now(),
        )
        definition.description = "second"
        definition.hidden = True
        definition.save(update_fields=["description"])

        saved = EnterprisePropertyDefinition.objects.get(pk=definition.pk)
        copies = PropertyDefinition.objects.get(pk=definition.pk)
        assert saved.description == "second"
        assert saved.hidden is False
        assert {source: copies.serializable_value(target) for source, target in PROPERTY_DEFINITION_COPIES.items()} == {
            source: saved.serializable_value(source) for source in PROPERTY_DEFINITION_COPIES
        }
