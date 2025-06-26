from typing import Any

from posthog.test.base import NonAtomicTestMigrations

import pytest

pytestmark = pytest.mark.skip("old migrations slow overall test run down")


class UpdateSurveyResponseMigrationTest(NonAtomicTestMigrations):
    migrate_from = "0420_alert"
    migrate_to = "0421_set_all_survey_responses_to_be_strings"

    CLASS_DATA_LEVEL_SETUP = False

    def setUpBeforeMigration(self, apps: Any) -> None:
        PropertyDefinition = apps.get_model("posthog", "PropertyDefinition")
        Organization = apps.get_model("posthog", "Organization")
        Team = apps.get_model("posthog", "Team")

        self.organization = Organization.objects.create(name="o1")
        self.team = Team.objects.create(organization=self.organization, name="t1")

        self.property_0 = PropertyDefinition.objects.create(
            team_id=self.team.id,
            name="$survey_response",
            property_type="Numeric",
            is_numerical=True,
        )
        self.property_1 = PropertyDefinition.objects.create(
            team_id=self.team.id, name="$survey_response_1", property_type="Numeric", is_numerical=True, type=1
        )
        self.property_2 = PropertyDefinition.objects.create(
            team_id=self.team.id, name="$survey_response_2", property_type="Numeric", is_numerical=True, type=1
        )
        self.property_3 = PropertyDefinition.objects.create(
            team_id=self.team.id, name="other_property", property_type="Numeric", is_numerical=True, type=1
        )
        self.property_4 = PropertyDefinition.objects.create(
            team_id=self.team.id, name="$survey_response_2", property_type="Numeric", is_numerical=True, type=2
        )

        self.property_before_migration = [
            {
                "id": self.property_0.id,
                "name": self.property_0.name,
                "property_type": self.property_0.property_type,
                "is_numerical": self.property_0.is_numerical,
                "type": self.property_0.type,
            },
            {
                "id": self.property_1.id,
                "name": self.property_1.name,
                "property_type": self.property_1.property_type,
                "is_numerical": self.property_1.is_numerical,
                "type": self.property_1.type,
            },
            {
                "id": self.property_2.id,
                "name": self.property_2.name,
                "property_type": self.property_2.property_type,
                "is_numerical": self.property_2.is_numerical,
                "type": self.property_2.type,
            },
            {
                "id": self.property_3.id,
                "name": self.property_3.name,
                "property_type": self.property_3.property_type,
                "is_numerical": self.property_3.is_numerical,
                "type": self.property_3.type,
            },
            {
                "id": self.property_4.id,
                "name": self.property_4.name,
                "property_type": self.property_4.property_type,
                "is_numerical": self.property_4.is_numerical,
                "type": self.property_4.type,
            },
        ]

    def test_migration(self) -> None:
        # Ensure self.apps is not None
        assert self.apps is not None

        PropertyDefinition = self.apps.get_model("posthog", "PropertyDefinition")

        # Check updated properties
        updated_property_0 = PropertyDefinition.objects.get(id=self.property_0.id)
        updated_property_1 = PropertyDefinition.objects.get(id=self.property_1.id)
        updated_property_2 = PropertyDefinition.objects.get(id=self.property_2.id)

        self.assertEqual(updated_property_0.property_type, "String")
        self.assertFalse(updated_property_0.is_numerical)

        self.assertEqual(updated_property_1.property_type, "String")
        self.assertFalse(updated_property_1.is_numerical)

        self.assertEqual(updated_property_2.property_type, "String")
        self.assertFalse(updated_property_2.is_numerical)

        # Check unchanged properties
        unchanged_property_1 = PropertyDefinition.objects.get(id=self.property_3.id)
        unchanged_property_2 = PropertyDefinition.objects.get(id=self.property_4.id)

        self.assertEqual(unchanged_property_1.property_type, "Numeric")
        self.assertTrue(unchanged_property_1.is_numerical)
        self.assertEqual(unchanged_property_2.property_type, "Numeric")
        self.assertTrue(unchanged_property_2.is_numerical)

    def tearDown(self) -> None:
        # Ensure self.apps is not None
        assert self.apps is not None

        PropertyDefinition = self.apps.get_model("posthog", "PropertyDefinition")
        PropertyDefinition.objects.all().delete()
        super().tearDown()
