from posthog.test.base import APIBaseTest


class TestStaticUrls(APIBaseTest):
    def test_default_static_site_serving(self):
        response = self.client.post("/static/empty.txt", follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"")

    def test_cdn_static_site_serving(self):
        with self.settings(CDN_URL="https://cdn.example.com"):
            response = self.client.get("/static/array.js", follow=True)
            self.assertRedirects(response, "https://cdn.example.com/static/array.js")
