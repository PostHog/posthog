from posthog.models.link import Link
from posthog.models.team import Team
from posthog.models.user import User
from posthog.test.base import BaseTest


class TestLinkModel(BaseTest):
    def setUp(self):
        super().setUp()
        org, team, user = User.objects.bootstrap("Test org", "test@posthog.com", None)
        self.team = team
        self.user = user
        self.org = org
        self.another_team = Team.objects.create(organization=self.org, name="Another Team")

    def test_get_link_by_id(self):
        # Create a link
        link = Link.objects.create(
            redirect_url="https://example.com", short_link_domain="hog.gg", short_code="abc123", team=self.team
        )

        # Test getting the link by ID
        retrieved_link = Link.get_link(team_id=self.team.id, link_id=link.id)
        self.assertEqual(retrieved_link.id, link.id)
        self.assertEqual(retrieved_link.redirect_url, "https://example.com")

        # Test non-existent ID
        non_existent_link = Link.get_link(team_id=self.team.id, link_id="non-existent-id")
        self.assertIsNone(non_existent_link)

        # Test with None team_id
        none_team_link = Link.get_link(team_id=None, link_id=link.id)
        self.assertIsNone(none_team_link)

    def test_get_links_for_team(self):
        # Create links for different teams
        for i in range(5):
            Link.objects.create(
                redirect_url=f"https://example{i}.com",
                short_link_domain="hog.gg",
                short_code=f"team1-{i}",
                team=self.team,
            )

        for i in range(3):
            Link.objects.create(
                redirect_url=f"https://anotherexample{i}.com",
                short_link_domain="hog.gg",
                short_code=f"team2-{i}",
                team=self.another_team,
            )

        # Test getting links for team 1
        team1_links = Link.get_links_for_team(self.team.id)
        self.assertEqual(len(team1_links), 5)

        # Test getting links for team 2
        team2_links = Link.get_links_for_team(self.another_team.id)
        self.assertEqual(len(team2_links), 3)

        # Test pagination
        team1_links_limited = Link.get_links_for_team(self.team.id, limit=2)
        self.assertEqual(len(team1_links_limited), 2)

        team1_links_offset = Link.get_links_for_team(self.team.id, offset=2)
        self.assertEqual(len(team1_links_offset), 3)

        # Test with None team_id
        none_team_links = Link.get_links_for_team(None)
        self.assertEqual(len(none_team_links), 0)

    def test_unique_constraint_violation(self):
        # Create a link
        Link.objects.create(
            redirect_url="https://example.com", short_link_domain="hog.gg", short_code="unique_test", team=self.team
        )

        # Try to create another link with the same domain and code
        with self.assertRaises(Exception):
            Link.objects.create(
                redirect_url="https://anotherexample.com",
                short_link_domain="hog.gg",
                short_code="unique_test",
                team=self.another_team,
            )

    def test_unique_constraint_valid_cases(self):
        # Create initial link
        Link.objects.create(
            redirect_url="https://example.com", short_link_domain="hog.gg", short_code="different_test", team=self.team
        )

        # Should be able to create with different domain
        Link.objects.create(
            redirect_url="https://example.com",
            short_link_domain="different.com",
            short_code="different_test",
            team=self.team,
        )

        # Should be able to create with different code
        Link.objects.create(
            redirect_url="https://example.com", short_link_domain="hog.gg", short_code="different_code", team=self.team
        )
