from django.conf import settings

from posthog.test.base import APIBaseTest


class TestStaticUrls(APIBaseTest):
    def test_default_static_site_serving(self):
        response = self.client.get("/static/empty.txt", follow=True)
        self.assertEqual(settings.IS_CDN_CONFIGURED, False)
        self.assertContains(settings.INSTALLED_APPS, "django.contrib.staticfiles")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.streaming_content, b"")

    def test_cdn_static_site_serving(self):
        with self.settings(CDN_URL="https://cdn.example.com", JS_URL="https://cdn.example.com"):
            response = self.client.get("/static/array.js", follow=True)
            self.assertEqual(settings.IS_CDN_CONFIGURED, True)
            self.assertNotContains(settings.INSTALLED_APPS, "django.contrib.staticfiles")
            self.assertRedirects(response, "https://cdn.example.com/static/array.js")
