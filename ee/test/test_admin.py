from rest_framework import status

from posthog.test.base import APIBaseTest


class TestAdminCloud(APIBaseTest):
    initial_cloud_mode = True

    def test_staff_can_view_django_admin(self):
        self.user.is_staff = True
        self.user.save()

        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertIn("Django administration", str(response.content))

    def test_non_staff_cant_view_django_admin(self):
        self.user.is_staff = False
        self.user.save()

        response = self.client.get("/admin/", follow=True)
        self.assertRedirects(response, "/login?next=/admin/")
