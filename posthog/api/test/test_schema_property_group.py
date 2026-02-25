from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status

from posthog.models import EventDefinition, EventSchema, Project, SchemaPropertyGroup, SchemaPropertyGroupProperty


class TestSchemaPropertyGroupAPI(APIBaseTest):
    def test_create_property_group_with_properties(self):
        response = self.client.post(
            f"/api/projects/{self.project.id}/schema_property_groups/",
            {
                "name": "User Info",
                "description": "Basic user information",
                "properties": [
                    {
                        "name": "user_id",
                        "property_type": "String",
                        "is_required": True,
                        "description": "User ID",
                    },
                    {
                        "name": "email",
                        "property_type": "String",
                        "is_required": False,
                        "description": "Email",
                    },
                ],
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["name"] == "User Info"
        assert data["description"] == "Basic user information"
        assert len(data["properties"]) == 2
        assert data["properties"][0]["name"] == "email"
        assert data["properties"][0]["is_required"] is False
        assert data["properties"][1]["name"] == "user_id"
        assert data["properties"][1]["is_required"] is True

    def test_create_property_group_with_is_optional_in_types(self):
        response = self.client.post(
            f"/api/projects/{self.project.id}/schema_property_groups/",
            {
                "name": "Super Props Group",
                "properties": [
                    {
                        "name": "team_id",
                        "property_type": "String",
                        "is_required": True,
                        "is_optional_in_types": True,
                        "description": "Set via super properties",
                    },
                    {
                        "name": "user_id",
                        "property_type": "String",
                        "is_required": True,
                        "is_optional_in_types": False,
                    },
                ],
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        team_id_prop = next(p for p in data["properties"] if p["name"] == "team_id")
        user_id_prop = next(p for p in data["properties"] if p["name"] == "user_id")
        assert team_id_prop["is_optional_in_types"] is True
        assert team_id_prop["is_required"] is True
        assert user_id_prop["is_optional_in_types"] is False

    def test_update_property_group_preserves_existing_properties(self):
        # Create initial property group
        property_group = SchemaPropertyGroup.objects.create(
            team=self.team, project=self.project, name="Test Group", description="Test"
        )
        prop1 = SchemaPropertyGroupProperty.objects.create(
            property_group=property_group, name="prop1", property_type="String"
        )
        prop2 = SchemaPropertyGroupProperty.objects.create(
            property_group=property_group, name="prop2", property_type="Numeric"
        )

        # Update: keep prop1, modify prop2, add prop3, delete nothing
        response = self.client.patch(
            f"/api/projects/{self.project.id}/schema_property_groups/{property_group.id}/",
            {
                "properties": [
                    {"id": str(prop1.id), "name": "prop1", "property_type": "String"},
                    {"id": str(prop2.id), "name": "prop2_updated", "property_type": "Numeric"},
                    {"name": "prop3", "property_type": "Boolean"},
                ]
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["properties"]) == 3

        # Properties are recreated with new IDs, check by name and values
        prop_names = {p["name"] for p in data["properties"]}
        assert "prop1" in prop_names
        assert "prop2_updated" in prop_names
        assert "prop3" in prop_names

        # Verify types are correct
        prop2_updated = next(p for p in data["properties"] if p["name"] == "prop2_updated")
        assert prop2_updated["property_type"] == "Numeric"
        prop3 = next(p for p in data["properties"] if p["name"] == "prop3")
        assert prop3["property_type"] == "Boolean"

    def test_update_property_group_deletes_removed_properties(self):
        # Create property group with 2 properties
        property_group = SchemaPropertyGroup.objects.create(team=self.team, project=self.project, name="Test Group")
        prop1 = SchemaPropertyGroupProperty.objects.create(
            property_group=property_group, name="prop1", property_type="String"
        )
        SchemaPropertyGroupProperty.objects.create(property_group=property_group, name="prop2", property_type="Numeric")

        # Update to only keep prop1
        response = self.client.patch(
            f"/api/projects/{self.project.id}/schema_property_groups/{property_group.id}/",
            {
                "properties": [
                    {"id": str(prop1.id), "name": "prop1", "property_type": "String"},
                ]
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["properties"]) == 1
        assert data["properties"][0]["name"] == "prop1"

    def test_unique_constraint_on_team_and_name(self):
        SchemaPropertyGroup.objects.create(team=self.team, project=self.project, name="Duplicate Name")

        response = self.client.post(
            f"/api/projects/{self.project.id}/schema_property_groups/",
            {"name": "Duplicate Name", "description": "Should fail"},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "already exists" in str(response.json())

    def test_property_name_accepts_nonstandard_names(self):
        """Non-standard property names (e.g., starting with numbers, containing spaces) should be accepted
        to support grandfathered property names that are already in use."""
        max_length_name = "a" * 200
        response = self.client.post(
            f"/api/projects/{self.project.id}/schema_property_groups/",
            {
                "name": "Test Group",
                "properties": [
                    {"name": "123startswithnumber", "property_type": "String"},
                    {"name": "has spaces", "property_type": "String"},
                    {"name": "has-dashes", "property_type": "String"},
                    {"name": "$special_prefix", "property_type": "String"},
                    {"name": max_length_name, "property_type": "String"},
                ],
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        property_names = {p["name"] for p in data["properties"]}
        assert "123startswithnumber" in property_names
        assert "has spaces" in property_names
        assert "has-dashes" in property_names
        assert "$special_prefix" in property_names
        assert max_length_name in property_names

    def test_property_name_rejects_empty(self):
        """Empty property names should be rejected."""
        response = self.client.post(
            f"/api/projects/{self.project.id}/schema_property_groups/",
            {
                "name": "Test Group",
                "properties": [
                    {"name": "", "property_type": "String"},
                ],
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        response_str = str(response.json()).lower()
        assert "blank" in response_str or "required" in response_str

    def test_property_name_rejects_too_long(self):
        """Property names over 200 characters should be rejected."""
        long_name = "a" * 201
        response = self.client.post(
            f"/api/projects/{self.project.id}/schema_property_groups/",
            {
                "name": "Test Group",
                "properties": [
                    {"name": long_name, "property_type": "String"},
                ],
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "200 characters or less" in str(response.json())

    def test_delete_property_group(self):
        property_group = SchemaPropertyGroup.objects.create(team=self.team, project=self.project, name="To Delete")
        SchemaPropertyGroupProperty.objects.create(property_group=property_group, name="prop1", property_type="String")

        response = self.client.delete(f"/api/projects/{self.project.id}/schema_property_groups/{property_group.id}/")

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not SchemaPropertyGroup.objects.filter(id=property_group.id).exists()
        # Properties should be cascade deleted
        assert not SchemaPropertyGroupProperty.objects.filter(property_group=property_group).exists()

    @parameterized.expand(
        [
            ("string_enum", "String", {"enum": ["active", "pending", "cancelled"]}),
            ("string_not_enum", "String", {"not": {"enum": ["test", "debug"]}}),
            ("numeric_inclusive_range", "Numeric", {"minimum": 0, "maximum": 100}),
            ("numeric_exclusive_range", "Numeric", {"exclusiveMinimum": 0, "exclusiveMaximum": 100}),
            ("numeric_min_only", "Numeric", {"minimum": 0}),
            ("numeric_max_only", "Numeric", {"maximum": 100}),
            ("numeric_mixed_bounds", "Numeric", {"minimum": 0, "exclusiveMaximum": 100}),
            ("string_null_rules", "String", None),
            ("numeric_null_rules", "Numeric", None),
            ("boolean_null_rules", "Boolean", None),
            ("datetime_null_rules", "DateTime", None),
        ]
    )
    def test_create_with_valid_validation_rules(self, _name, property_type, validation_rules):
        response = self.client.post(
            f"/api/projects/{self.project.id}/schema_property_groups/",
            {
                "name": f"Group {_name}",
                "properties": [
                    {
                        "name": "prop",
                        "property_type": property_type,
                        "validation_rules": validation_rules,
                    },
                ],
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        prop = response.json()["properties"][0]
        assert prop["validation_rules"] == validation_rules

    @parameterized.expand(
        [
            ("enum_on_numeric", "Numeric", {"enum": ["a", "b"]}, "Unrecognized keys"),
            ("enum_on_boolean", "Boolean", {"enum": ["true"]}, "not supported"),
            ("enum_on_datetime", "DateTime", {"enum": ["2021-01-01"]}, "not supported"),
            ("range_on_string", "String", {"minimum": 0}, "Unrecognized keys"),
            ("empty_enum", "String", {"enum": []}, "must not be empty"),
            ("non_string_enum_values", "String", {"enum": [1, 2, 3]}, "must be strings"),
            ("both_minimum_and_exclusive", "Numeric", {"minimum": 0, "exclusiveMinimum": 0}, "Cannot specify both"),
            ("both_maximum_and_exclusive", "Numeric", {"maximum": 100, "exclusiveMaximum": 100}, "Cannot specify both"),
            ("lower_greater_than_upper", "Numeric", {"minimum": 100, "maximum": 50}, "must be less than"),
            ("lower_equal_to_upper", "Numeric", {"minimum": 50, "maximum": 50}, "must be less than"),
            ("non_numeric_bound", "Numeric", {"minimum": "abc"}, "must be a number"),
            ("both_enum_and_not", "String", {"enum": ["a"], "not": {"enum": ["b"]}}, "Cannot specify both"),
            ("not_without_enum", "String", {"not": {"min": 0}}, "exactly one key"),
            ("unrecognized_key", "Numeric", {"minimum": 0, "pattern": "abc"}, "Unrecognized keys"),
            ("object_with_rules", "Object", {"enum": ["a"]}, "not supported"),
        ]
    )
    def test_create_with_invalid_validation_rules(self, _name, property_type, validation_rules, expected_error):
        response = self.client.post(
            f"/api/projects/{self.project.id}/schema_property_groups/",
            {
                "name": f"Group {_name}",
                "properties": [
                    {
                        "name": "prop",
                        "property_type": property_type,
                        "validation_rules": validation_rules,
                    },
                ],
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert expected_error in str(response.json())

    def test_round_trip_validation_rules(self):
        rules = {"enum": ["active", "pending"]}
        create_resp = self.client.post(
            f"/api/projects/{self.project.id}/schema_property_groups/",
            {
                "name": "Round Trip Group",
                "properties": [
                    {"name": "status", "property_type": "String", "validation_rules": rules},
                ],
            },
        )
        assert create_resp.status_code == status.HTTP_201_CREATED
        group_id = create_resp.json()["id"]

        get_resp = self.client.get(f"/api/projects/{self.project.id}/schema_property_groups/{group_id}/")
        assert get_resp.status_code == status.HTTP_200_OK
        prop = get_resp.json()["properties"][0]
        assert prop["validation_rules"] == rules

    def test_update_with_validation_rules(self):
        property_group = SchemaPropertyGroup.objects.create(
            team=self.team, project=self.project, name="Update Rules Group"
        )
        prop = SchemaPropertyGroupProperty.objects.create(
            property_group=property_group, name="status", property_type="String"
        )

        response = self.client.patch(
            f"/api/projects/{self.project.id}/schema_property_groups/{property_group.id}/",
            {
                "properties": [
                    {
                        "id": str(prop.id),
                        "name": "status",
                        "property_type": "String",
                        "validation_rules": {"enum": ["a", "b"]},
                    },
                ],
            },
        )

        assert response.status_code == status.HTTP_200_OK
        updated_prop = response.json()["properties"][0]
        assert updated_prop["validation_rules"] == {"enum": ["a", "b"]}

    def test_list_includes_events(self):
        # Create property group
        property_group = SchemaPropertyGroup.objects.create(team=self.team, project=self.project, name="Test Group")

        # Create event and associate it
        event_def = EventDefinition.objects.create(team=self.team, project=self.project, name="test_event")
        EventSchema.objects.create(event_definition=event_def, property_group=property_group)

        response = self.client.get(f"/api/projects/{self.project.id}/schema_property_groups/")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        property_groups = data["results"] if "results" in data else data

        test_group = next((pg for pg in property_groups if pg["id"] == str(property_group.id)), None)
        assert test_group is not None
        assert "events" in test_group
        assert len(test_group["events"]) == 1
        assert test_group["events"][0]["name"] == "test_event"


class TestEventSchemaAPI(APIBaseTest):
    def test_create_event_schema(self):
        property_group = SchemaPropertyGroup.objects.create(team=self.team, project=self.project, name="Test Group")
        event_def = EventDefinition.objects.create(team=self.team, project=self.project, name="test_event")

        response = self.client.post(
            f"/api/projects/{self.project.id}/event_schemas/",
            {
                "event_definition": event_def.id,
                "property_group_id": str(property_group.id),
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["property_group"]["id"] == str(property_group.id)

    def test_prevent_duplicate_event_schema(self):
        property_group = SchemaPropertyGroup.objects.create(team=self.team, project=self.project, name="Test Group")
        event_def = EventDefinition.objects.create(team=self.team, project=self.project, name="test_event")

        # Create first event schema
        EventSchema.objects.create(event_definition=event_def, property_group=property_group)

        # Try to create duplicate
        response = self.client.post(
            f"/api/projects/{self.project.id}/event_schemas/",
            {
                "event_definition": event_def.id,
                "property_group_id": str(property_group.id),
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        # Check that it's a uniqueness error
        response_data = response.json()
        assert "unique" in str(response_data).lower()

    def test_delete_event_schema(self):
        property_group = SchemaPropertyGroup.objects.create(team=self.team, project=self.project, name="Test Group")
        event_def = EventDefinition.objects.create(team=self.team, project=self.project, name="test_event")
        event_schema = EventSchema.objects.create(event_definition=event_def, property_group=property_group)

        response = self.client.delete(f"/api/projects/{self.project.id}/event_schemas/{event_schema.id}/")

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not EventSchema.objects.filter(id=event_schema.id).exists()

    def test_cross_team_property_group_rejection(self):
        other_project, other_team = Project.objects.create_with_team(
            organization=self.organization,
            name="Other Project",
            initiating_user=self.user,
            team_fields={"name": "Other Team"},
        )
        other_property_group = SchemaPropertyGroup.objects.create(
            team=other_team, project=other_project, name="Other Team Group"
        )
        event_def = EventDefinition.objects.create(team=self.team, project=self.project, name="test_event")

        response = self.client.post(
            f"/api/projects/{self.project.id}/event_schemas/",
            {"event_definition": event_def.id, "property_group_id": str(other_property_group.id)},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "does not exist" in str(response.json())

    def test_cross_team_event_definition_rejection(self):
        other_project, other_team = Project.objects.create_with_team(
            organization=self.organization,
            name="Other Project",
            initiating_user=self.user,
            team_fields={"name": "Other Team"},
        )
        other_event_def = EventDefinition.objects.create(
            team=other_team, project=other_project, name="other_team_event"
        )
        property_group = SchemaPropertyGroup.objects.create(team=self.team, project=self.project, name="Test Group")

        response = self.client.post(
            f"/api/projects/{self.project.id}/event_schemas/",
            {"event_definition": other_event_def.id, "property_group_id": str(property_group.id)},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "does not exist" in str(response.json())
