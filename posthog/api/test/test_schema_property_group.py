from posthog.test.base import APIBaseTest

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

    def test_property_name_validation(self):
        response = self.client.post(
            f"/api/projects/{self.project.id}/schema_property_groups/",
            {
                "name": "Test Group",
                "properties": [
                    {"name": "123invalid", "property_type": "String"},
                ],
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "must start with a letter or underscore" in str(response.json())

    def test_delete_property_group(self):
        property_group = SchemaPropertyGroup.objects.create(team=self.team, project=self.project, name="To Delete")
        SchemaPropertyGroupProperty.objects.create(property_group=property_group, name="prop1", property_type="String")

        response = self.client.delete(f"/api/projects/{self.project.id}/schema_property_groups/{property_group.id}/")

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not SchemaPropertyGroup.objects.filter(id=property_group.id).exists()
        # Properties should be cascade deleted
        assert not SchemaPropertyGroupProperty.objects.filter(property_group=property_group).exists()

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
