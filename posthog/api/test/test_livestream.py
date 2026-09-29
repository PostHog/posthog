from datetime import timedelta

from posthog.test.base import APIBaseTest

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.jwt import PosthogJwtAudience, encode_jwt
from posthog.models import OrganizationMembership

from products.access_control.backend.models.access_control import AccessControl


class TestLivestreamAuthorization(APIBaseTest):
    def _token(self, audience: PosthogJwtAudience = PosthogJwtAudience.LIVESTREAM) -> str:
        return encode_jwt(
            {
                "user_id": self.user.id,
                "team_id": self.team.id,
                "organization_id": str(self.organization.id),
                "api_token": self.team.api_token,
            },
            timedelta(days=7),
            audience,
        )

    @parameterized.expand([("membership", 403), ("project_access", 403), ("user", 401), ("project_token", 401)])
    def test_rechecks_current_access(self, revoked: str, expected_status: int) -> None:
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self.organization.available_product_features = [{"key": AvailableFeature.ACCESS_CONTROL}]
        self.organization.save()
        headers = {"HTTP_AUTHORIZATION": f"Bearer {self._token()}"}
        initial = self.client.get("/api/livestream/authorize/", **headers)
        self.assertEqual(initial.status_code, 204)
        self.assertEqual(initial["Cache-Control"], "no-store")

        if revoked == "membership":
            self.organization_membership.delete()
        elif revoked == "project_access":
            AccessControl.objects.create(
                team=self.team, resource="project", resource_id=str(self.team.id), access_level="none"
            )
        elif revoked == "user":
            self.user.is_active = False
            self.user.save(update_fields=["is_active"])
        else:
            self.team.api_token = "test-rotated-project-token"
            self.team.save(update_fields=["api_token"])

        self.assertEqual(self.client.get("/api/livestream/authorize/", **headers).status_code, expected_status)

    @parameterized.expand([(None,), (PosthogJwtAudience.IMPERSONATED_USER,)])
    def test_rejects_other_authentication(self, audience: PosthogJwtAudience | None) -> None:
        headers = {"HTTP_AUTHORIZATION": f"Bearer {self._token(audience)}"} if audience else {}
        self.assertEqual(self.client.get("/api/livestream/authorize/", **headers).status_code, 401)
