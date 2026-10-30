import pytest
from posthog.test.base import BaseTest

from django.db import connection
from django.utils import timezone

from products.event_definitions.backend.models.enterprise_copies import EVENT_DEFINITION_COPIED_FIELDS

from ee.models.event_definition import EnterpriseEventDefinition


class TestEventDefinition(BaseTest):
    def test_errors_on_invalid_verified_by_type(self):
        with pytest.raises(ValueError):
            EnterpriseEventDefinition.objects.create(
                team=self.team,
                name="enterprise event",
                owner=self.user,
                verified_by="Not user id",  # type: ignore
            )

    def test_default_verified_false(self):
        eventDef = EnterpriseEventDefinition.objects.create(team=self.team, name="enterprise event", owner=self.user)
        assert eventDef.verified is False

    def test_save_keeps_base_copies_equal_to_enterprise_fields(self):
        definition = EnterpriseEventDefinition.objects.create(
            team=self.team,
            name="enterprise definition",
            description="first",
            owner=self.user,
            verified=True,
            verified_by=self.user,
            verified_at=timezone.now(),
            default_columns=["plan"],
        )
        definition.description = "second"
        definition.hidden = True
        definition.save(update_fields=["description"])

        saved = EnterpriseEventDefinition.objects.get(pk=definition.pk)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT description, owner_id, updated_at, updated_by_id, verified, verified_at, verified_by_id, hidden, default_columns FROM posthog_eventdefinition WHERE id = %s",
                [saved.pk],
            )
            copies = cursor.fetchone()
        assert saved.description == "second"
        assert saved.hidden is False
        assert copies == tuple(saved.serializable_value(name) for name in EVENT_DEFINITION_COPIED_FIELDS)
