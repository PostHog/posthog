from contextlib import nullcontext

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.models import SessionRecording, SharingConfiguration

from products.dashboards.backend.models.dashboard import Dashboard
from products.notebooks.backend.models import Notebook
from products.product_analytics.backend.facade.models import Insight


class TestShareLinkAuthorizationAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.insight = Insight.objects.create(team=self.team, name="Shared insight", created_by=self.user)
        self.dashboard = Dashboard.objects.create(team=self.team, name="Shared dashboard", created_by=self.user)
        self.notebook = Notebook.objects.create(team=self.team, title="Shared notebook", created_by=self.user)
        self.recording = SessionRecording.objects.create(team=self.team, session_id="shared-recording")
        self.fga = MagicMock()
        self.fga.client_batch_check.side_effect = lambda checks, options: [
            MagicMock(allowed=False, error=None) for check in checks
        ]
        for patcher in (
            patch("products.authz.backend.logic.rollout.get_feature_flag_or_none", return_value="v1"),
            patch("products.authz.backend.logic.authorization.ready_state", return_value=b"ready:test"),
            patch(
                "products.authz.backend.logic.authorization.pooled_openfga_client",
                side_effect=lambda: nullcontext(self.fga),
            ),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client.logout()

    @parameterized.expand(["insight", "dashboard", "notebook", "recording"])
    def test_public_page_requires_an_openfga_grant(self, field: str) -> None:
        config = SharingConfiguration.objects.create(team=self.team, enabled=True, **{field: getattr(self, field)})
        response = self.client.get(f"/shared/{config.access_token}.json")
        assert response.status_code == 404, response.content

    def test_valid_share_token_cannot_bypass_openfga_on_insight_api_reads(self) -> None:
        config = SharingConfiguration.objects.create(team=self.team, enabled=True, insight=self.insight)
        assert config.access_token is not None
        response = self.client.get(
            f"/api/projects/{self.team.id}/insights/{self.insight.id}/",
            {"sharing_access_token": config.access_token},
        )
        assert response.status_code == 403, response.content
