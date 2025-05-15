from posthog.models.link import Link
from posthog.models.team import Team
from posthog.test.base import BaseTest


class TestLinkModel(BaseTest):
    def setUp(self):
        super().setUp()
        self.team = Team.objects.create(name="Test Team")
        self.another_team = Team.objects.create(name="Another Team")

    def test_str(self):
        link = Link.objects.create(
            redirect_url="https://example.com", short_link_domain="hog.gg", short_code="abc123", team=self.team
        )
        self.assertEqual(str(link), f"{link.id} -> https://example.com")

    def test_get_link_by_id(self):
        # Create a link
        link = Link.objects.create(
            redirect_url="https://example.com", short_link_domain="hog.gg", short_code="abc123", team=self.team
        )

        # Test getting the link by ID
        retrieved_link = Link.get_link(link_id=link.id)
        self.assertEqual(retrieved_link.id, link.id)
        self.assertEqual(retrieved_link.redirect_url, "https://example.com")

        # Test non-existent ID
        non_existent_link = Link.get_link(link_id="non-existent-id")
        self.assertIsNone(non_existent_link)

    def test_get_link_by_domain_and_code(self):
        # Create a link
        Link.objects.create(
            redirect_url="https://example.com", short_link_domain="hog.gg", short_code="abc123", team=self.team
        )

        # Test getting the link by domain and short code
        retrieved_link = Link.get_link(short_link_domain="hog.gg", short_code="abc123")
        self.assertIsNotNone(retrieved_link)
        self.assertEqual(retrieved_link.redirect_url, "https://example.com")

        # Test non-existent domain and code
        non_existent_link = Link.get_link(short_link_domain="nonexistent.com", short_code="nonexistent")
        self.assertIsNone(non_existent_link)

    def test_get_link_with_team_filter(self):
        # Create two links with different teams
        link1 = Link.objects.create(
            redirect_url="https://example1.com", short_link_domain="hog.gg", short_code="team1", team=self.team
        )

        Link.objects.create(
            redirect_url="https://example2.com", short_link_domain="hog.gg", short_code="team2", team=self.another_team
        )

        # Test filtering by team
        retrieved_link = Link.get_link(short_link_domain="hog.gg", short_code="team1", team_id=self.team.id)
        self.assertEqual(retrieved_link.id, link1.id)

        # Test filtering by wrong team
        retrieved_link = Link.get_link(short_link_domain="hog.gg", short_code="team1", team_id=self.another_team.id)
        self.assertIsNone(retrieved_link)

    def test_delete_link_by_id(self):
        # Create a link
        link = Link.objects.create(
            redirect_url="https://example.com", short_link_domain="hog.gg", short_code="delete_test", team=self.team
        )

        # Verify link exists
        self.assertTrue(Link.objects.filter(id=link.id).exists())

        # Delete link by ID
        result = Link.delete_link(link_id=link.id)
        self.assertTrue(result)

        # Verify link is deleted
        self.assertFalse(Link.objects.filter(id=link.id).exists())

        # Test deleting non-existent link
        result = Link.delete_link(link_id="non-existent-id")
        self.assertFalse(result)

    def test_delete_link_by_domain_and_code(self):
        # Create a link
        Link.objects.create(
            redirect_url="https://example.com", short_link_domain="hog.gg", short_code="delete_test_2", team=self.team
        )

        # Verify link exists
        self.assertTrue(Link.objects.filter(short_link_domain="hog.gg", short_code="delete_test_2").exists())

        # Delete link by domain and code
        result = Link.delete_link(short_link_domain="hog.gg", short_code="delete_test_2")
        self.assertTrue(result)

        # Verify link is deleted
        self.assertFalse(Link.objects.filter(short_link_domain="hog.gg", short_code="delete_test_2").exists())

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

    def test_get_short_url(self):
        # Create a link
        link = Link.objects.create(
            redirect_url="https://example.com", short_link_domain="hog.gg", short_code="short", team=self.team
        )

        # Test getting the short URL
        self.assertEqual(link.get_short_url(), "https://hog.gg/short")

        # Test with different domain and code
        link2 = Link.objects.create(
            redirect_url="https://example.com",
            short_link_domain="link.posthog.com",
            short_code="abc123",
            team=self.team,
        )

        self.assertEqual(link2.get_short_url(), "https://link.posthog.com/abc123")

    def test_unique_constraint(self):
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

        # Should be able to create with different domain
        Link.objects.create(
            redirect_url="https://example.com",
            short_link_domain="different.com",
            short_code="unique_test",
            team=self.team,
        )

        # Should be able to create with different code
        Link.objects.create(
            redirect_url="https://example.com", short_link_domain="hog.gg", short_code="different_code", team=self.team
        )
