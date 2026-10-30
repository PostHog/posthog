import pytest
from posthog.test.base import BaseTest

from django.db import connection
from django.utils import timezone

from products.event_definitions.backend.models.enterprise_copies import PROPERTY_DEFINITION_COPIED_FIELDS

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
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT description, updated_at, updated_by_id, verified, verified_at, verified_by_id, hidden FROM posthog_propertydefinition WHERE id = %s",
                [saved.pk],
            )
            copies = cursor.fetchone()
        assert saved.description == "second"
        assert saved.hidden is False
        assert copies == tuple(saved.serializable_value(name) for name in PROPERTY_DEFINITION_COPIED_FIELDS)
