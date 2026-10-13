from collections.abc import Sequence
from io import StringIO
from uuid import UUID

from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings

from structlog.testing import capture_logs

from posthog.models import Organization, OrganizationMembership, Team, User

from products.authz.backend.facade.contracts import CheckRequest
from products.authz.backend.logic import rollout
from products.authz.backend.management.commands.benchmark_authorization import summarize


class TestAuthorizationBenchmarkStats(SimpleTestCase):
    def test_summarize_interpolates_percentiles_and_uses_sample_standard_deviation(self) -> None:
        summary = summarize([1.0, 2.0, 3.0, 4.0])

        self.assertEqual(summary["mean"], 2.5)
        self.assertEqual(summary["median"], 2.5)
        self.assertAlmostEqual(summary["stddev"], 1.2909944487)
        self.assertAlmostEqual(summary["p90"], 3.7)
        self.assertAlmostEqual(summary["p95"], 3.85)
        self.assertAlmostEqual(summary["p99"], 3.97)


@override_settings(DEBUG=True)
class TestAuthorizationBenchmarkCommand(TestCase):
    def test_bootstraps_request_data_and_rolls_it_back_after_counting_batches(self) -> None:
        output = StringIO()
        organization_ids: list[UUID] = []
        client = MagicMock()
        client.get_store_id.return_value = None

        def check(requests: Sequence[CheckRequest]) -> list[bool]:
            request = requests[0]
            organization = Organization.objects.get(id=request.resource.organization_id)
            team = Team.objects.get(id=request.resource.project_id, organization=organization)
            assert request.subject is not None
            user = User.objects.get(id=request.subject.user_id)
            membership = OrganizationMembership.objects.get(organization=organization, user=user)
            organization_ids.append(organization.id)
            self.assertEqual(team.organization_id, organization.id)
            self.assertEqual(membership.level, OrganizationMembership.Level.OWNER)
            self.assertTrue(user.is_active)
            rollout.logger.info("authz_decision_comparison", mode="test")
            return [True] * len(requests)

        with capture_logs() as logs:
            with (
                patch(
                    "products.authz.backend.management.commands.benchmark_authorization.bootstrap_openfga",
                    return_value="model",
                ),
                patch(
                    "products.authz.backend.management.commands.benchmark_authorization.api.synchronize_organization"
                ) as synchronize,
                patch(
                    "products.authz.backend.management.commands.benchmark_authorization.api.check", side_effect=check
                ),
                patch(
                    "products.authz.backend.management.commands.benchmark_authorization.get_openfga_client",
                    return_value=client,
                ),
                patch("products.authz.backend.management.commands.benchmark_authorization.redis.get_client"),
            ):
                call_command(
                    "benchmark_authorization",
                    requests=5,
                    batch_size=2,
                    warmup_batches=1,
                    modes=["v1"],
                    stdout=output,
                )

        self.assertIn("5/5 allowed", output.getvalue())
        self.assertFalse(any(log["event"] == "authz_decision_comparison" for log in logs))
        self.assertTrue(organization_ids)
        synchronize.assert_called_once_with(organization_ids[0])
        self.assertFalse(Organization.objects.filter(id=organization_ids[0]).exists())
