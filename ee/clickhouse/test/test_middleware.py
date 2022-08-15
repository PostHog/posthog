import json

from ee.api.test.base import APILicensedTest
from posthog.models import User


class TestQueryMiddleware(APILicensedTest):
    def test_query(self):
        self.user.is_staff = True
        self.user.save()
        response = self.client.get(
            f'/api/projects/{self.team.id}/insights/trend/?events={json.dumps([{"id": "$pageview"}])}'
        )
        self.assertEqual(response.status_code, 200)
        response = self.client.get("/api/debug_ch_queries/").json()
        self.assertIn("SELECT", response[0]["query"])  # type: ignore

        #  Test saving queries if we're impersonating a user
        user2 = User.objects.create_and_join(organization=self.organization, email="test", password="bla")
        self.client.post("/admin/login/user/{}/".format(user2.pk))
        self.client.get(f'/api/projects/{self.team.id}/insights/trend/?events={json.dumps([{"id": "$pageleave"}])}')

        response = self.client.get("/api/debug_ch_queries/").json()
        self.assertIn("SELECT", response[0]["query"])  # type: ignore
