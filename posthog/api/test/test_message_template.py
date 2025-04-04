from rest_framework import status

from posthog.models import MessageTemplate
from posthog.test.base import APIBaseTest


class TestMessageTemplate(APIBaseTest):
    def test_list_message_templates(self):
        template1 = MessageTemplate.objects.create(
            team=self.team,
            name="Test Template 1",
            description="Test Description 1",
            type="email",
            content={
                "email": {
                    "value": {
                        "to": "{person.properties.email}",
                        "from": "test@posthog.com",
                        "body": "Hi {person.properties.name}",
                        "html": "<p>Hi {person.properties.name}</p>",
                        "subject": "Test Subject",
                    }
                }
            },
        )

        template2 = MessageTemplate.objects.create(
            team=self.team,
            name="Test Template 2",
            description="Test Description 2",
            type="email",
            content={
                "email": {
                    "value": {
                        "to": "{person.properties.email}",
                        "from": "test@posthog.com",
                        "body": "Hello {person.properties.name}",
                        "html": "<p>Hello {person.properties.name}</p>",
                        "subject": "Another Subject",
                    }
                }
            },
        )

        # Create a deleted template that shouldn't show up
        MessageTemplate.objects.create(
            team=self.team,
            name="Deleted Template",
            description="Deleted Description",
            type="email",
            deleted=True,
            content={"email": {"value": {}}},
        )

        response = self.client.get("/api/message_templates/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data["results"]), 2)

        # Verify first template
        template1_result = next(r for r in data["results"] if r["id"] == str(template1.id))
        self.assertEqual(template1_result["name"], "Test Template 1")
        self.assertEqual(template1_result["description"], "Test Description 1")
        self.assertEqual(template1_result["type"], "email")
        self.assertEqual(template1_result["content"]["email"]["value"]["subject"], "Test Subject")

        # Verify second template
        template2_result = next(r for r in data["results"] if r["id"] == str(template2.id))
        self.assertEqual(template2_result["name"], "Test Template 2")
        self.assertEqual(template2_result["description"], "Test Description 2")
        self.assertEqual(template2_result["type"], "email")
        self.assertEqual(template2_result["content"]["email"]["value"]["subject"], "Another Subject")

    def test_retrieve_message_template(self):
        template = MessageTemplate.objects.create(
            team=self.team,
            name="Test Template",
            description="Test Description",
            type="email",
            content={
                "email": {
                    "value": {
                        "to": "{person.properties.email}",
                        "from": "test@posthog.com",
                        "body": "Hi {person.properties.name}",
                        "html": "<p>Hi {person.properties.name}</p>",
                        "subject": "Test Subject",
                    }
                }
            },
        )

        response = self.client.get(f"/api/message_templates/{template.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["name"], "Test Template")
        self.assertEqual(data["description"], "Test Description")
        self.assertEqual(data["type"], "email")
        self.assertEqual(data["content"]["email"]["value"]["subject"], "Test Subject")

    def test_create_message_template(self):
        response = self.client.post(
            "/api/message_templates/",
            {
                "name": "New Template",
                "description": "New Description",
                "type": "email",
                "content": {
                    "email": {
                        "value": {
                            "to": "{person.properties.email}",
                            "from": "test@posthog.com",
                            "body": "Hi {person.properties.name}",
                            "html": "<p>Hi {person.properties.name}</p>",
                            "subject": "New Subject",
                        }
                    }
                },
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        data = response.json()
        self.assertEqual(data["name"], "New Template")
        self.assertEqual(data["description"], "New Description")
        self.assertEqual(data["type"], "email")
        self.assertEqual(data["content"]["email"]["value"]["subject"], "New Subject")

        # Verify it was created in the database
        template = MessageTemplate.objects.get(id=data["id"])
        self.assertEqual(template.name, "New Template")
        self.assertEqual(template.type, "email")
        self.assertEqual(template.content["email"]["value"]["subject"], "New Subject")

    def test_update_message_template(self):
        template = MessageTemplate.objects.create(
            team=self.team,
            name="Test Template",
            description="Test Description",
            type="email",
            content={
                "email": {
                    "value": {
                        "to": "{person.properties.email}",
                        "from": "test@posthog.com",
                        "body": "Hi {person.properties.name}",
                        "html": "<p>Hi {person.properties.name}</p>",
                        "subject": "Test Subject",
                    }
                }
            },
        )

        response = self.client.patch(
            f"/api/message_templates/{template.id}/",
            {"name": "Updated Template", "content": {"email": {"value": {"subject": "Updated Subject"}}}},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["name"], "Updated Template")
        self.assertEqual(data["content"]["email"]["value"]["subject"], "Updated Subject")

        # Original fields should be preserved
        self.assertEqual(data["type"], "email")
        self.assertEqual(data["description"], "Test Description")
        self.assertEqual(data["content"]["email"]["value"]["body"], "Hi {person.properties.name}")

    def test_soft_delete_message_template(self):
        template = MessageTemplate.objects.create(
            team=self.team,
            name="Test Template",
            description="Test Description",
            type="email",
            content={"email": {"value": {}}},
        )

        response = self.client.patch(f"/api/message_templates/{template.id}/", {"deleted": True})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Template should be marked as deleted but still exist
        template.refresh_from_db()
        self.assertTrue(template.deleted)

        # Template should not appear in list
        response = self.client.get("/api/message_templates/")
        self.assertEqual(len(response.json()["results"]), 0)

    def test_restore_message_template(self):
        template = MessageTemplate.objects.create(
            team=self.team,
            name="Test Template",
            description="Test Description",
            type="email",
            content={"email": {"value": {}}},
            deleted=True,
        )

        response = self.client.patch(f"/api/message_templates/{template.id}/", {"deleted": False})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Template should be marked as not deleted
        template.refresh_from_db()
        self.assertFalse(template.deleted)

        # Template should appear in list
        response = self.client.get("/api/message_templates/")
        self.assertEqual(len(response.json()["results"]), 1)

    def test_cannot_hard_delete_message_template(self):
        template = MessageTemplate.objects.create(
            team=self.team,
            name="Test Template",
            description="Test Description",
            type="email",
            content={"email": {"value": {}}},
        )

        response = self.client.delete(f"/api/message_templates/{template.id}/")
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

        # Template should still exist
        self.assertTrue(MessageTemplate.objects.filter(id=template.id).exists())

    def test_filter_message_templates_by_type(self):
        # Create email template
        email_template = MessageTemplate.objects.create(
            team=self.team, name="Email Template", type="email", content={"email": {"value": {}}}
        )

        # Create templates of other types if we add them in the future
        # For now, we only have email type

        response = self.client.get("/api/message_templates/?type=email")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["id"], str(email_template.id))
        self.assertEqual(data["results"][0]["type"], "email")
