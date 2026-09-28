from typing import Any
from uuid import uuid4

from posthog.test.base import TestMigrations


class TestDefaultPinnedPropertiesMigration(TestMigrations):
    @property
    def app(self) -> str:
        return "customer_analytics"

    migrate_from = "0059_teamcustomeranalyticsconfig_default_pinned_properties"
    migrate_to = "0060_inherit_default_pinned_properties"

    def setUpBeforeMigration(self, apps: Any) -> None:
        config_model = apps.get_model("customer_analytics", "UserCustomerAnalyticsConfig")
        self.empty_config_id = config_model.objects.create(
            team_id=self.team.id,
            user_id=self.user.id,
            properties={"pinned_properties": [], "future_setting": "kept"},
            pinned_custom_property_definition_ids=[],
        ).id
        self.personal_config_id = config_model.objects.create(
            team_id=self.team.id,
            user_id=self.user.id + 1,
            properties={
                "pinned_properties": [{"kind": "custom_property", "id": str(uuid4())}],
                "future_setting": "kept",
            },
            pinned_custom_property_definition_ids=[],
        ).id
        legacy_id = uuid4()
        self.legacy_config_id = config_model.objects.create(
            team_id=self.team.id,
            user_id=self.user.id + 2,
            properties={"pinned_properties": [], "future_setting": "kept"},
            pinned_custom_property_definition_ids=[legacy_id],
        ).id
        self.keyless_config_id = config_model.objects.create(
            team_id=self.team.id,
            user_id=self.user.id + 3,
            properties={"future_setting": "kept"},
            pinned_custom_property_definition_ids=[],
        ).id

    def test_only_historical_empty_pins_become_inherited(self) -> None:
        assert self.apps is not None
        config_model = self.apps.get_model("customer_analytics", "UserCustomerAnalyticsConfig")

        empty_config = config_model.objects.get(id=self.empty_config_id)
        self.assertEqual(empty_config.properties, {"future_setting": "kept"})

        personal_config = config_model.objects.get(id=self.personal_config_id)
        self.assertEqual(len(personal_config.properties["pinned_properties"]), 1)
        self.assertEqual(personal_config.properties["future_setting"], "kept")

        legacy_config = config_model.objects.get(id=self.legacy_config_id)
        self.assertEqual(legacy_config.properties["pinned_properties"], [])
        self.assertEqual(legacy_config.properties["future_setting"], "kept")

        keyless_config = config_model.objects.get(id=self.keyless_config_id)
        self.assertEqual(keyless_config.properties, {"future_setting": "kept"})
