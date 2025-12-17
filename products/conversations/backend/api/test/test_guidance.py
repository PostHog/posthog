"""Tests for guidance rules API endpoints."""

from posthog.test.base import APIBaseTest

from rest_framework import status

from products.conversations.backend.models import GuidanceRule


class TestGuidanceRuleViewSet(APIBaseTest):
    """Tests for guidance rule API endpoints."""

    def setUp(self):
        super().setUp()
        self.url = f"/api/projects/{self.team.id}/conversations/guidance/"

    def test_list_guidance_rules(self):
        """Should list all guidance rules for the team."""
        rule1 = GuidanceRule.objects.create(
            team=self.team,
            rule_type="tone",
            name="Be helpful",
            content="Always greet customers warmly",
            is_active=True,
            created_by=self.user,
        )
        rule2 = GuidanceRule.objects.create(
            team=self.team,
            rule_type="escalation",
            name="Escalation triggers",
            content="Escalate when customer is angry",
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
        GuidanceRule.objects.create(
            team=self.team,
            rule_type="tone",
            name="Team 1 Rule",
            content="Content",
            is_active=True,
            created_by=self.user,
        )

        other_team = self.organization.teams.create()
        GuidanceRule.objects.create(
            team=other_team,
            rule_type="tone",
            name="Other Team Rule",
            content="Content",
            is_active=True,
        )

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["name"], "Team 1 Rule")

    def test_create_guidance_rule(self):
        """Should create a new guidance rule."""
        response = self.client.post(
            self.url,
            data={
                "rule_type": "tone",
                "name": "New Rule",
                "content": "Rule content here",
                "is_active": True,
                "channels": ["widget"],
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        data = response.json()
        self.assertEqual(data["rule_type"], "tone")
        self.assertEqual(data["name"], "New Rule")
        self.assertEqual(data["channels"], ["widget"])

    def test_update_guidance_rule(self):
        """Should update an existing rule."""
        rule = GuidanceRule.objects.create(
            team=self.team,
            rule_type="tone",
            name="Original Name",
            content="Original content",
            is_active=True,
            created_by=self.user,
        )

        response = self.client.patch(
            f"{self.url}{rule.id}/",
            data={"name": "Updated Name"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        rule.refresh_from_db()
        self.assertEqual(rule.name, "Updated Name")

    def test_delete_guidance_rule(self):
        """Should delete a rule."""
        rule = GuidanceRule.objects.create(
            team=self.team,
            rule_type="tone",
            name="To Delete",
            content="Content",
            is_active=True,
            created_by=self.user,
        )

        response = self.client.delete(f"{self.url}{rule.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(GuidanceRule.objects.filter(id=rule.id).exists())

    def test_filter_by_is_active(self):
        """Should filter rules by is_active."""
        GuidanceRule.objects.create(
            team=self.team,
            rule_type="tone",
            name="Active Rule",
            content="Content",
            is_active=True,
            created_by=self.user,
        )
        GuidanceRule.objects.create(
            team=self.team,
            rule_type="tone",
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
            rule_type="tone",
            name="Tone Rule",
            content="Content",
            is_active=True,
            created_by=self.user,
        )
        GuidanceRule.objects.create(
            team=self.team,
            rule_type="escalation",
            name="Escalation Rule",
            content="Content",
            is_active=True,
            created_by=self.user,
        )

        response = self.client.get(f"{self.url}?rule_type=escalation")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["rule_type"], "escalation")

    def test_search_by_name(self):
        """Should search rules by name."""
        GuidanceRule.objects.create(
            team=self.team,
            rule_type="tone",
            name="Greeting Guidelines",
            content="Content",
            is_active=True,
            created_by=self.user,
        )
        GuidanceRule.objects.create(
            team=self.team,
            rule_type="tone",
            name="FAQ Responses",
            content="Content",
            is_active=True,
            created_by=self.user,
        )

        response = self.client.get(f"{self.url}?search=greeting")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["name"], "Greeting Guidelines")

    def test_channels_field_accepts_list(self):
        """channels field should accept a list of valid channel strings."""
        channels = ["widget", "email", "slack"]

        response = self.client.post(
            self.url,
            data={
                "rule_type": "tone",
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
        """channels can be empty."""
        response = self.client.post(
            self.url,
            data={
                "rule_type": "escalation",
                "name": "All channels rule",
                "content": "Content",
                "is_active": True,
                "channels": [],
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        data = response.json()
        self.assertEqual(data["channels"], [])

    def test_created_by_is_set_automatically(self):
        """created_by should be set to current user."""
        response = self.client.post(
            self.url,
            data={
                "rule_type": "tone",
                "name": "Test Rule",
                "content": "Content",
                "is_active": True,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        data = response.json()
        self.assertEqual(data["created_by"]["id"], self.user.id)
