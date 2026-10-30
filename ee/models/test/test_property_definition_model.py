import pytest
from posthog.test.base import BaseTest

from django.db import connection
from django.utils import timezone

from posthog.models import User

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

    def test_deleting_a_user_clears_their_id_from_the_base_copies(self):
        other = User.objects.create_and_join(self.organization, "copied-user@example.com", None)
        definition = EnterprisePropertyDefinition.objects.create(
            team=self.team, name="owned definition", updated_by=other, verified_by=other
        )

        other.delete()

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT updated_by_id, verified_by_id FROM posthog_propertydefinition WHERE id = %s", [definition.pk]
            )
            assert cursor.fetchone() == (
                None,
                None,
            )
