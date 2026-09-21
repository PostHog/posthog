from typing import Any

from posthog.test.base import NonAtomicTestMigrations


class BackfillTaggedItemGenericPointerTest(NonAtomicTestMigrations):
    migrate_from = "1369_taggeditem_legacy_reverse_accessors"
    migrate_to = "1373_taggeditem_generic_pointer_unique"

    def setUpBeforeMigration(self, apps: Any) -> None:
        tag_model = apps.get_model("posthog", "Tag")
        tagged_item_model = apps.get_model("posthog", "TaggedItem")
        dashboard_model = apps.get_model("dashboards", "Dashboard")
        event_definition_model = apps.get_model("event_definitions", "EventDefinition")

        self.tag_team_id = self.team.id
        tag = tag_model.objects.create(name="tag", team_id=self.team.id)
        self.dashboard = dashboard_model.objects.create(team_id=self.team.id, name="dashboard")
        self.event_definition = event_definition_model.objects.create(team_id=self.team.id, name="event")

        # Historical models skip TaggedItem.save(), so these rows start with no generic pointer,
        # like rows written before the pointer columns existed.
        self.dashboard_item = tagged_item_model.objects.create(tag=tag, dashboard_id=self.dashboard.id)
        self.event_definition_item = tagged_item_model.objects.create(
            tag=tag, event_definition_id=self.event_definition.id
        )

    def test_backfill_fills_the_generic_pointer(self) -> None:
        assert self.apps is not None
        tagged_item_model = self.apps.get_model("posthog", "TaggedItem")
        content_type_model = self.apps.get_model("contenttypes", "ContentType")

        dashboard_item = tagged_item_model.objects.get(pk=self.dashboard_item.pk)
        assert (
            dashboard_item.content_type_id
            == content_type_model.objects.get(app_label="dashboards", model="dashboard").id
        )
        assert dashboard_item.object_id == self.dashboard.id
        assert dashboard_item.object_uuid is None
        assert dashboard_item.team_id == self.tag_team_id

        event_definition_item = tagged_item_model.objects.get(pk=self.event_definition_item.pk)
        assert (
            event_definition_item.content_type_id
            == content_type_model.objects.get(app_label="event_definitions", model="eventdefinition").id
        )
        assert event_definition_item.object_uuid == self.event_definition.id
        assert event_definition_item.object_id is None
        assert event_definition_item.team_id == self.tag_team_id
