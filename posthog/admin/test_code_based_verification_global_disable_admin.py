from posthog.test.base import APIBaseTest

from rest_framework import status
from rest_framework.test import APIRequestFactory, force_authenticate

from posthog.admin.admins.code_based_verification_bypass_admin import CodeBasedVerificationGlobalDisableViewSet
from posthog.helpers.two_factor_session import (
    MAX_CODE_BASED_VERIFICATION_GLOBAL_DISABLE_TTL_SECONDS,
    clear_code_based_verification_global_disable,
    is_code_based_verification_globally_disabled,
)


class TestCodeBasedVerificationGlobalDisableAdmin(APIBaseTest):
    def setUp(self):
        super().setUp()
        clear_code_based_verification_global_disable()
        self.factory = APIRequestFactory()

    def tearDown(self):
        clear_code_based_verification_global_disable()
        super().tearDown()

    def _make_staff(self):
        self.user.is_staff = True
        self.user.save()

    def test_non_staff_is_forbidden(self):
        request = self.factory.get("/admin/api/code-based-verification-global-disable/")
        force_authenticate(request, user=self.user)
        response = CodeBasedVerificationGlobalDisableViewSet.as_view({"get": "list"})(request)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_can_disable_list_and_clear(self):
        self._make_staff()

        request = self.factory.post(
            "/admin/api/code-based-verification-global-disable/",
            {"reason": "email outage", "ttl_seconds": 3600},
            format="json",
        )
        force_authenticate(request, user=self.user)
        response = CodeBasedVerificationGlobalDisableViewSet.as_view({"post": "create"})(request)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(is_code_based_verification_globally_disabled())
        self.assertEqual(response.data["state"]["disabled_by"], self.user.email)
        self.assertEqual(response.data["state"]["reason"], "email outage")

        request = self.factory.get("/admin/api/code-based-verification-global-disable/")
        force_authenticate(request, user=self.user)
        response = CodeBasedVerificationGlobalDisableViewSet.as_view({"get": "list"})(request)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["disabled"])

        request = self.factory.delete("/admin/api/code-based-verification-global-disable/")
        force_authenticate(request, user=self.user)
        response = CodeBasedVerificationGlobalDisableViewSet.as_view({"delete": "destroy"})(request)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(is_code_based_verification_globally_disabled())

    def test_reason_is_required(self):
        self._make_staff()
        request = self.factory.post(
            "/admin/api/code-based-verification-global-disable/", {"reason": "", "ttl_seconds": 3600}, format="json"
        )
        force_authenticate(request, user=self.user)
        response = CodeBasedVerificationGlobalDisableViewSet.as_view({"post": "create"})(request)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(is_code_based_verification_globally_disabled())

    def test_ttl_cap_is_enforced(self):
        self._make_staff()
        request = self.factory.post(
            "/admin/api/code-based-verification-global-disable/",
            {"reason": "too long", "ttl_seconds": MAX_CODE_BASED_VERIFICATION_GLOBAL_DISABLE_TTL_SECONDS + 1},
            format="json",
        )
        force_authenticate(request, user=self.user)
        response = CodeBasedVerificationGlobalDisableViewSet.as_view({"post": "create"})(request)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(is_code_based_verification_globally_disabled())
