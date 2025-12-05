"""Tests for guidance rules API endpoints."""

from freezegun import freeze_time
from posthog.test.base import APIBaseTest

from rest_framework import status

from products.conversations.backend.models import GuidanceRule


class TestGuidanceRuleViewSet(APIBaseTest):
    """Tests for authenticated guidance rule API endpoints."""

    def setUp(self):
        super().setUp()
        self.url = f"/api/projects/{self.team.id}/conversations/guidance/"

    def test_list_guidance_rules(self):
        """Should list all guidance rules for the team."""
        rule1 = GuidanceRule.objects.create(
            team=self.team,
            rule_type="system_prompt",
            name="Be helpful and friendly",
            content="Always greet customers warmly",
            is_active=True,
            created_by=self.user,
        )
        rule2 = GuidanceRule.objects.create(
            team=self.team,
            rule_type="knowledge_base",
            name="Product features",
            content="Our product includes X, Y, Z",
            is_active=True,
            created_by=self.user,
        )

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data["results"]), 2)

        rule_ids = [r["id"] for r in data["results"]]
        self.assertIn(str(rule1.id), rule_ids)
        self.assertIn(str(rule2.id), rule_ids)

    def test_rules_isolated_by_team(self):
        """Should only see rules from own team."""
        rule1 = GuidanceRule.objects.create(
            team=self.team,
            rule_type="system_prompt",
            name="Team 1 Rule",
            content="Content for team 1",
            is_active=True,
            created_by=self.user,
        )

        # Create rule in another team
        other_team = self.organization.teams.create()
        GuidanceRule.objects.create(
            team=other_team,
            rule_type="system_prompt",
            name="Team 2 Rule",
            content="Content for team 2",
            is_active=True,
            created_by=self.user,
        )

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["id"], str(rule1.id))

    def test_retrieve_guidance_rule(self):
        """Should retrieve a specific guidance rule."""
        rule = GuidanceRule.objects.create(
            team=self.team,
            rule_type="system_prompt",
            name="Test Rule",
            content="This is the rule content",
            is_active=True,
            channels=["widget", "email"],
            created_by=self.user,
        )

        response = self.client.get(f"{self.url}{rule.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["id"], str(rule.id))
        self.assertEqual(data["rule_type"], "system_prompt")
        self.assertEqual(data["name"], "Test Rule")
        self.assertEqual(data["content"], "This is the rule content")
        self.assertTrue(data["is_active"])
        self.assertEqual(data["channels"], ["widget", "email"])
        self.assertEqual(data["created_by"]["id"], self.user.id)

    def test_cannot_retrieve_rule_from_another_team(self):
        """Should not be able to retrieve rule from another team."""
        other_team = self.organization.teams.create()
        rule = GuidanceRule.objects.create(
            team=other_team,
            rule_type="system_prompt",
            name="Other Team Rule",
            content="Content",
            is_active=True,
            created_by=self.user,
        )

        response = self.client.get(f"{self.url}{rule.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_create_guidance_rule(self):
        """Should be able to create a new guidance rule."""
        response = self.client.post(
            self.url,
            data={
                "rule_type": "system_prompt",
                "name": "New Rule",
                "content": "Rule content here",
                "is_active": True,
                "channels": ["widget"],
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        data = response.json()
        self.assertEqual(data["rule_type"], "system_prompt")
        self.assertEqual(data["name"], "New Rule")
        self.assertEqual(data["content"], "Rule content here")
        self.assertTrue(data["is_active"])
        self.assertEqual(data["channels"], ["widget"])

        # Verify rule was created in database
        rule = GuidanceRule.objects.get(id=data["id"])
        self.assertEqual(rule.name, "New Rule")
        self.assertEqual(rule.team, self.team)

    def test_created_by_is_set_automatically(self):
        """created_by should be set to current user on create."""
        response = self.client.post(
            self.url,
            data={
                "rule_type": "knowledge_base",
                "name": "New Rule",
                "content": "Content",
                "is_active": True,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        data = response.json()
        self.assertEqual(data["created_by"]["id"], self.user.id)

        # Verify in database
        rule = GuidanceRule.objects.get(id=data["id"])
        self.assertEqual(rule.created_by, self.user)

    def test_cannot_override_created_by(self):
        """Should not be able to override created_by field."""
        other_user = self.organization.members.create(email="other@example.com")

        response = self.client.post(
            self.url,
            data={
                "rule_type": "system_prompt",
                "name": "New Rule",
                "content": "Content",
                "is_active": True,
                "created_by": other_user.id,  # Try to override
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        data = response.json()
        # Should still be current user, not other_user
        self.assertEqual(data["created_by"]["id"], self.user.id)

    def test_update_guidance_rule(self):
        """Should be able to update a guidance rule."""
        rule = GuidanceRule.objects.create(
            team=self.team,
            rule_type="system_prompt",
            name="Original Name",
            content="Original content",
            is_active=True,
            created_by=self.user,
        )

        response = self.client.patch(
            f"{self.url}{rule.id}/",
            data={
                "name": "Updated Name",
                "content": "Updated content",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["name"], "Updated Name")
        self.assertEqual(data["content"], "Updated content")

        # Verify in database
        rule.refresh_from_db()
        self.assertEqual(rule.name, "Updated Name")
        self.assertEqual(rule.content, "Updated content")

    def test_update_is_active_flag(self):
        """Should be able to activate/deactivate rules."""
        rule = GuidanceRule.objects.create(
            team=self.team,
            rule_type="system_prompt",
            name="Test Rule",
            content="Content",
            is_active=True,
            created_by=self.user,
        )

        response = self.client.patch(
            f"{self.url}{rule.id}/",
            data={"is_active": False},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        rule.refresh_from_db()
        self.assertFalse(rule.is_active)

    def test_update_rule_type(self):
        """Should be able to update rule_type."""
        rule = GuidanceRule.objects.create(
            team=self.team,
            rule_type="system_prompt",
            name="Test Rule",
            content="Content",
            is_active=True,
            created_by=self.user,
        )

        response = self.client.patch(
            f"{self.url}{rule.id}/",
            data={"rule_type": "knowledge_base"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        rule.refresh_from_db()
        self.assertEqual(rule.rule_type, "knowledge_base")

    def test_update_channels(self):
        """Should be able to update channels."""
        rule = GuidanceRule.objects.create(
            team=self.team,
            rule_type="system_prompt",
            name="Test Rule",
            content="Content",
            is_active=True,
            channels=["widget"],
            created_by=self.user,
        )

        response = self.client.patch(
            f"{self.url}{rule.id}/",
            data={"channels": ["widget", "email", "chat"]},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        rule.refresh_from_db()
        self.assertEqual(rule.channels, ["widget", "email", "chat"])

    def test_cannot_update_readonly_fields(self):
        """Should not be able to update read-only fields."""
        rule = GuidanceRule.objects.create(
            team=self.team,
            rule_type="system_prompt",
            name="Test Rule",
            content="Content",
            is_active=True,
            created_by=self.user,
        )

        with freeze_time("2024-01-01"):
            original_created_at = rule.created_at

        with freeze_time("2024-02-01"):
            response = self.client.patch(
                f"{self.url}{rule.id}/",
                data={
                    "created_at": "2024-12-31T00:00:00Z",
                    "updated_at": "2024-12-31T00:00:00Z",
                },
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Fields should not have changed
        rule.refresh_from_db()
        self.assertEqual(rule.created_at, original_created_at)

    def test_delete_guidance_rule(self):
        """Should be able to delete a guidance rule."""
        rule = GuidanceRule.objects.create(
            team=self.team,
            rule_type="system_prompt",
            name="Test Rule",
            content="Content",
            is_active=True,
            created_by=self.user,
        )

        response = self.client.delete(f"{self.url}{rule.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        self.assertFalse(GuidanceRule.objects.filter(id=rule.id).exists())

    def test_filter_by_is_active_true(self):
        """Should filter rules by is_active=true."""
        GuidanceRule.objects.create(
            team=self.team,
            rule_type="system_prompt",
            name="Active Rule",
            content="Content",
            is_active=True,
            created_by=self.user,
        )
        GuidanceRule.objects.create(
            team=self.team,
            rule_type="system_prompt",
            name="Inactive Rule",
            content="Content",
            is_active=False,
            created_by=self.user,
        )

        response = self.client.get(f"{self.url}?is_active=true")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["name"], "Active Rule")

    def test_filter_by_is_active_false(self):
        """Should filter rules by is_active=false."""
        GuidanceRule.objects.create(
            team=self.team,
            rule_type="system_prompt",
            name="Active Rule",
            content="Content",
            is_active=True,
            created_by=self.user,
        )
        GuidanceRule.objects.create(
            team=self.team,
            rule_type="system_prompt",
            name="Inactive Rule",
            content="Content",
            is_active=False,
            created_by=self.user,
        )

        response = self.client.get(f"{self.url}?is_active=false")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["name"], "Inactive Rule")

    def test_filter_by_rule_type(self):
        """Should filter rules by rule_type."""
        GuidanceRule.objects.create(
            team=self.team,
            rule_type="system_prompt",
            name="System Prompt Rule",
            content="Content",
            is_active=True,
            created_by=self.user,
        )
        GuidanceRule.objects.create(
            team=self.team,
            rule_type="knowledge_base",
            name="Knowledge Base Rule",
            content="Content",
            is_active=True,
            created_by=self.user,
        )
        GuidanceRule.objects.create(
            team=self.team,
            rule_type="escalation_trigger",
            name="Escalation Rule",
            content="Content",
            is_active=True,
            created_by=self.user,
        )

        response = self.client.get(f"{self.url}?rule_type=knowledge_base")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["rule_type"], "knowledge_base")

    def test_search_by_name(self):
        """Should search rules by name."""
        GuidanceRule.objects.create(
            team=self.team,
            rule_type="system_prompt",
            name="Greeting Guidelines",
            content="Content",
            is_active=True,
            created_by=self.user,
        )
        GuidanceRule.objects.create(
            team=self.team,
            rule_type="system_prompt",
            name="FAQ Responses",
            content="Content",
            is_active=True,
            created_by=self.user,
        )
        GuidanceRule.objects.create(
            team=self.team,
            rule_type="system_prompt",
            name="Greeting Advanced Tips",
            content="Content",
            is_active=True,
            created_by=self.user,
        )

        response = self.client.get(f"{self.url}?search=greeting")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data["results"]), 2)
        names = [r["name"] for r in data["results"]]
        self.assertIn("Greeting Guidelines", names)
        self.assertIn("Greeting Advanced Tips", names)

    def test_search_is_case_insensitive(self):
        """Search should be case-insensitive."""
        GuidanceRule.objects.create(
            team=self.team,
            rule_type="system_prompt",
            name="Greeting Guidelines",
            content="Content",
            is_active=True,
            created_by=self.user,
        )

        response = self.client.get(f"{self.url}?search=GREETING")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data["results"]), 1)

    def test_ordering_by_created_at_desc(self):
        """Rules should be ordered by created_at descending."""
        with freeze_time("2024-01-01"):
            rule1 = GuidanceRule.objects.create(
                team=self.team,
                rule_type="system_prompt",
                name="Oldest Rule",
                content="Content",
                is_active=True,
                created_by=self.user,
            )

        with freeze_time("2024-01-03"):
            rule2 = GuidanceRule.objects.create(
                team=self.team,
                rule_type="system_prompt",
                name="Newest Rule",
                content="Content",
                is_active=True,
                created_by=self.user,
            )

        with freeze_time("2024-01-02"):
            rule3 = GuidanceRule.objects.create(
                team=self.team,
                rule_type="system_prompt",
                name="Middle Rule",
                content="Content",
                is_active=True,
                created_by=self.user,
            )

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        rule_ids = [r["id"] for r in data["results"]]

        # Should be ordered by most recent first
        self.assertEqual(rule_ids[0], str(rule2.id))
        self.assertEqual(rule_ids[1], str(rule3.id))
        self.assertEqual(rule_ids[2], str(rule1.id))

    def test_pagination_default_limit(self):
        """Should paginate with default limit of 100."""
        # Create 150 rules
        for i in range(150):
            GuidanceRule.objects.create(
                team=self.team,
                rule_type="system_prompt",
                name=f"Rule {i}",
                content="Content",
                is_active=True,
                created_by=self.user,
            )

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data["results"]), 100)
        self.assertIsNotNone(data["next"])

    def test_pagination_custom_limit(self):
        """Should support custom limit parameter."""
        # Create 50 rules
        for i in range(50):
            GuidanceRule.objects.create(
                team=self.team,
                rule_type="system_prompt",
                name=f"Rule {i}",
                content="Content",
                is_active=True,
                created_by=self.user,
            )

        response = self.client.get(f"{self.url}?limit=25")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data["results"]), 25)

    def test_pagination_offset(self):
        """Should support offset parameter."""
        with freeze_time("2024-01-01"):
            rule1 = GuidanceRule.objects.create(
                team=self.team,
                rule_type="system_prompt",
                name="First Rule",
                content="Content",
                is_active=True,
                created_by=self.user,
            )

        with freeze_time("2024-01-02"):
            GuidanceRule.objects.create(
                team=self.team,
                rule_type="system_prompt",
                name="Second Rule",
                content="Content",
                is_active=True,
                created_by=self.user,
            )

        # Get second page (offset=1, limit=1)
        response = self.client.get(f"{self.url}?limit=1&offset=1")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["id"], str(rule1.id))

    def test_pagination_max_limit(self):
        """Should respect max limit of 1000."""
        # Create 1500 rules
        for i in range(1500):
            GuidanceRule.objects.create(
                team=self.team,
                rule_type="system_prompt",
                name=f"Rule {i}",
                content="Content",
                is_active=True,
                created_by=self.user,
            )

        # Try to request 2000, should be capped at 1000
        response = self.client.get(f"{self.url}?limit=2000")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data["results"]), 1000)

    def test_unauthenticated_request_fails(self):
        """Unauthenticated requests should fail."""
        self.client.logout()

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_combined_filters(self):
        """Should support multiple filters at once."""
        GuidanceRule.objects.create(
            team=self.team,
            rule_type="system_prompt",
            name="Greeting Guidelines",
            content="Content",
            is_active=True,
            created_by=self.user,
        )
        GuidanceRule.objects.create(
            team=self.team,
            rule_type="system_prompt",
            name="Greeting Advanced",
            content="Content",
            is_active=False,
            created_by=self.user,
        )
        GuidanceRule.objects.create(
            team=self.team,
            rule_type="knowledge_base",
            name="Greeting Base",
            content="Content",
            is_active=True,
            created_by=self.user,
        )

        # Filter by rule_type AND is_active AND search
        response = self.client.get(f"{self.url}?rule_type=system_prompt&is_active=true&search=greeting")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["name"], "Greeting Guidelines")

    def test_channels_field_accepts_list(self):
        """channels field should accept a list of strings."""
        channels = ["widget", "email", "chat", "api"]

        response = self.client.post(
            self.url,
            data={
                "rule_type": "system_prompt",
                "name": "Multi-channel rule",
                "content": "Content",
                "is_active": True,
                "channels": channels,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        data = response.json()
        self.assertEqual(data["channels"], channels)

    def test_empty_channels_allowed(self):
        """channels can be empty or null."""
        response = self.client.post(
            self.url,
            data={
                "rule_type": "system_prompt",
                "name": "No channel rule",
                "content": "Content",
                "is_active": True,
                "channels": [],
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        data = response.json()
        self.assertEqual(data["channels"], [])

    def test_created_by_includes_user_details(self):
        """created_by should include user details via UserBasicSerializer."""
        rule = GuidanceRule.objects.create(
            team=self.team,
            rule_type="system_prompt",
            name="Test Rule",
            content="Content",
            is_active=True,
            created_by=self.user,
        )

        response = self.client.get(f"{self.url}{rule.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertIn("created_by", data)
        self.assertIn("id", data["created_by"])
        self.assertIn("email", data["created_by"])
        self.assertEqual(data["created_by"]["id"], self.user.id)
        self.assertEqual(data["created_by"]["email"], self.user.email)

    def test_different_rule_types(self):
        """Should handle different rule_type values."""
        rule_types = ["system_prompt", "knowledge_base", "escalation_trigger"]

        for rule_type in rule_types:
            response = self.client.post(
                self.url,
                data={
                    "rule_type": rule_type,
                    "name": f"{rule_type} Rule",
                    "content": "Content",
                    "is_active": True,
                },
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)

            data = response.json()
            self.assertEqual(data["rule_type"], rule_type)

        # Verify all were created
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 3)
