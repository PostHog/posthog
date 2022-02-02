from django.conf import settings

from posthog.test.base import APIBaseTest


class TestStaticUrls(APIBaseTest):
    def test_default_static_site_serving(self):
        response = self.client.get("/static/empty.txt", follow=True)
        self.assertEqual(settings.IS_CDN_CONFIGURED, False)
        contains_staticfiles = "django.contrib.staticfiles" in settings.INSTALLED_APPS
        self.assertEqual(contains_staticfiles, True)
        self.assertEqual(response.status_code, 200)

    def test_cdn_static_site_serving(self):
        cdn_domain = "https://cdn.example.com"
        with self.settings(CDN_URL=cdn_domain, IS_CDN_CONFIGURED=True, JS_URL=cdn_domain):
            response = self.client.get("/static/array.js", follow=True)
            self.assertRedirects(response, "https://cdn.example.com/static/array.js")
