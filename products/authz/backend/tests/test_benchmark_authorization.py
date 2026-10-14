from collections.abc import Sequence
from io import StringIO
from uuid import UUID

from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings

from structlog.testing import capture_logs

from posthog.models import Organization, OrganizationMembership, Team, User

from products.access_control.backend.models.access_control import AccessControl
from products.authz.backend.facade.contracts import CheckRequest
from products.authz.backend.logic import authorization, legacy_authorization, rollout
from products.authz.backend.management.commands.benchmark_authorization import measure_checkers, summarize


class TestAuthorizationBenchmarkStats(SimpleTestCase):
    def test_summarize_interpolates_percentiles_and_uses_sample_standard_deviation(self) -> None:
        summary = summarize([1.0, 2.0, 3.0, 4.0])

        self.assertEqual(summary["mean"], 2.5)
        self.assertEqual(summary["median"], 2.5)
        self.assertAlmostEqual(summary["stddev"], 1.2909944487)
        self.assertAlmostEqual(summary["p90"], 3.7)
        self.assertAlmostEqual(summary["p95"], 3.85)
        self.assertAlmostEqual(summary["p99"], 3.97)

    def test_component_timings_accumulate_separately_and_reset_for_each_batch(self) -> None:
        with (
            patch(
                "products.authz.backend.management.commands.benchmark_authorization.time.perf_counter_ns",
                side_effect=[0, 2_000_000, 2_000_000, 5_000_000, 5_000_000, 9_000_000],
            ),
            measure_checkers("HIGHER_CONSISTENCY") as timings,
        ):
            assert authorization.check([], None) == []
            assert legacy_authorization.check([], None) == []
            assert authorization.check([], None) == []
        assert timings == {"OpenFGA": 6.0, "Legacy": 3.0}
        with measure_checkers("MINIMIZE_LATENCY") as next_batch:
            assert next_batch == {}


@override_settings(DEBUG=True)
class TestAuthorizationBenchmarkCommand(TestCase):
    def test_bootstraps_request_data_and_rolls_it_back_after_counting_batches(self) -> None:
        output = StringIO()
        organization_ids: list[UUID] = []
        request_shapes: set[tuple[int, str | None]] = set()
        client = MagicMock()
        client.get_store_id.return_value = None

        def check(requests: Sequence[CheckRequest]) -> list[bool]:
            for request in requests:
                organization = Organization.objects.get(id=request.resource.organization_id)
                team = Team.objects.get(id=request.resource.project_id, organization=organization)
                assert request.subject is not None
                user = User.objects.get(id=request.subject.user_id)
                membership = OrganizationMembership.objects.get(organization=organization, user=user)
                organization_ids.append(organization.id)
                request_shapes.add((user.id, request.resource.id))
                self.assertEqual(team.organization_id, organization.id)
                self.assertEqual(membership.level, OrganizationMembership.Level.MEMBER)
                self.assertTrue(user.is_active)
                self.assertGreater(AccessControl.objects.filter(team=team).count(), 100)
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
        self.assertGreater(len({user_id for user_id, _ in request_shapes}), 1)
        self.assertIn(None, {resource_id for _, resource_id in request_shapes})
        self.assertGreater(len({resource_id for _, resource_id in request_shapes if resource_id}), 1)
        synchronize.assert_called_once_with(organization_ids[0])
        self.assertFalse(Organization.objects.filter(id=organization_ids[0]).exists())
