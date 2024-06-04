from typing import Any

from posthog.test.base import NonAtomicTestMigrations


class UpdateSurveyResponseMigrationTest(NonAtomicTestMigrations):
    migrate_from = "0419_remove_organization_available_features"
    migrate_to = "0420_set_all_survey_responses_to_be_strings"

    def setUpBeforeMigration(self, apps: Any) -> None:
        PropertyDefinition = apps.get_model("posthog", "PropertyDefinition")

        self.property_1 = PropertyDefinition.objects.create(
            team_id=self.team.id, name="$survey_response_1", property_type="Numeric", is_numerical=True
        )
        self.property_2 = PropertyDefinition.objects.create(
            team_id=self.team.id, name="$survey_response_2", property_type="Numeric", is_numerical=True
        )
        self.property_3 = PropertyDefinition.objects.create(
            team_id=self.team.id, name="other_property", property_type="Numeric", is_numerical=True
        )

        self.property_before_migration = [
            {
                "id": self.property_1.id,
                "name": self.property_1.name,
                "property_type": self.property_1.property_type,
                "is_numerical": self.property_1.is_numerical,
            },
            {
                "id": self.property_2.id,
                "name": self.property_2.name,
                "property_type": self.property_2.property_type,
                "is_numerical": self.property_2.is_numerical,
            },
            {
                "id": self.property_3.id,
                "name": self.property_3.name,
                "property_type": self.property_3.property_type,
                "is_numerical": self.property_3.is_numerical,
            },
        ]

    def test_migration(self) -> None:
        # Ensure self.apps is not None
        assert self.apps is not None

        PropertyDefinition = self.apps.get_model("posthog", "PropertyDefinition")

        # Check updated properties
        updated_property_1 = PropertyDefinition.objects.get(id=self.property_1.id)
        updated_property_2 = PropertyDefinition.objects.get(id=self.property_2.id)

        self.assertEqual(updated_property_1.property_type, "String")
        self.assertFalse(updated_property_1.is_numerical)

        self.assertEqual(updated_property_2.property_type, "String")
        self.assertFalse(updated_property_2.is_numerical)

        # Check unchanged property
        unchanged_property = PropertyDefinition.objects.get(id=self.property_3.id)
        self.assertEqual(unchanged_property.property_type, "Numeric")
        self.assertTrue(unchanged_property.is_numerical)

    def tearDown(self) -> None:
        # Ensure self.apps is not None
        assert self.apps is not None

        PropertyDefinition = self.apps.get_model("posthog", "PropertyDefinition")
        PropertyDefinition.objects.all().delete()
        super().tearDown()
        super().tearDown()
        super().tearDown()
