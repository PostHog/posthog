import pytest
from posthog.test.base import BaseTest

from django.utils import timezone

from products.event_definitions.backend.models.enterprise_copies import EVENT_DEFINITION_COPIES
from products.event_definitions.backend.models.event_definition import EventDefinition

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
        copies = EventDefinition.objects.get(pk=definition.pk)
        opts = EnterpriseEventDefinition._meta
        assert saved.description == "second"
        assert saved.hidden is False
        assert {
            source: getattr(copies, opts.get_field(target).attname)
            for source, target in EVENT_DEFINITION_COPIES.items()
        } == {source: getattr(saved, opts.get_field(source).attname) for source in EVENT_DEFINITION_COPIES}
