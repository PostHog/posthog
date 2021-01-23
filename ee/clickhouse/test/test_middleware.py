from posthog.api.test.base import APIBaseTest
from posthog.models import User


class TestQueryMiddleware(APIBaseTest):
    TESTS_API = True

    def test_query(self):
        self.user.is_staff = True
        self.user.save()
        response = self.client.get('/api/insight/trend/?events=[{"id": "$pageview"}]')
        self.assertEqual(response.status_code, 200)
        response = self.client.get("/api/debug_ch_queries/").json()
        self.assertIn("SELECT", response[0]["query"])  # type: ignore

        #  Test saving queries if we're impersonating a user
        user2 = User.objects.create_and_join(organization=self.organization, email="test", password="bla")
        self.client.post("/admin/login/user/{}/".format(user2.pk))
        self.client.get('/api/insight/trend/?events=[{"id": "$pageleave"}]')

        response = self.client.get("/api/debug_ch_queries/").json()
        self.assertIn("SELECT", response[0]["query"])  # type: ignore
