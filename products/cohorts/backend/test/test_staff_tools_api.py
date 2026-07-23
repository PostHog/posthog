from datetime import timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.models import Organization, Team

from products.cohorts.backend.models.cohort import Cohort


class TestCohortsStaffToolsAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.user.is_staff = True
        self.user.save()

    def _create_cross_org_cohort(self, **kwargs) -> Cohort:
        other_org = Organization.objects.create(name="Unrelated Org")
        other_team = Team.objects.create(organization=other_org, name="Cross Org Team")
        self.assertFalse(self.user.organization_memberships.filter(organization=other_org).exists())
        return Cohort.objects.create(team=other_team, name="Cross Org Cohort", **kwargs)

    @parameterized.expand(
        [
            ("lookup", "get", "/api/cohorts_staff/?cohort_ids=1"),
            ("stuck", "get", "/api/cohorts_staff/stuck/"),
            ("recalculate", "post", "/api/cohorts_staff/recalculate/"),
        ]
    )
    def test_non_staff_user_gets_403(self, _name, method, url):
        self.user.is_staff = False
        self.user.save()

        response = getattr(self.client, method)(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_lookup_returns_cohort_from_organization_staff_user_does_not_belong_to(self):
        # The whole point of this endpoint: staff must reach cohorts in teams they aren't a
        # member of. Guards against someone reintroducing membership scoping on the viewset.
        cohort = self._create_cross_org_cohort(
            is_calculating=True,
            last_calculation=timezone.now() - timedelta(hours=2),
            errors_calculating=3,
            version=4,
            pending_version=5,
            count=123,
        )

        response = self.client.get(f"/api/cohorts_staff/?cohort_ids={cohort.id},999999999")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["not_found_cohort_ids"], [999999999])
        (result,) = data["results"]
        self.assertEqual(result["id"], cohort.id)
        self.assertEqual(result["name"], "Cross Org Cohort")
        self.assertEqual(result["team_id"], cohort.team_id)
        self.assertEqual(result["team_name"], "Cross Org Team")
        self.assertEqual(result["project_id"], cohort.team.project_id)
        self.assertTrue(result["is_calculating"])
        self.assertEqual(result["errors_calculating"], 3)
        self.assertEqual(result["version"], 4)
        self.assertEqual(result["pending_version"], 5)
        self.assertEqual(result["count"], 123)

    def test_lookup_rejects_more_than_max_cohorts(self):
        cohort_ids = ",".join(str(i) for i in range(1, 52))
        response = self.client.get(f"/api/cohorts_staff/?cohort_ids={cohort_ids}")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_lookup_includes_deleted_cohorts(self):
        cohort = Cohort.objects.create(team=self.team, name="Deleted Cohort", deleted=True)

        response = self.client.get(f"/api/cohorts_staff/?cohort_ids={cohort.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        (result,) = response.json()["results"]
        self.assertTrue(result["deleted"])

    def test_stuck_returns_only_stuck_dynamic_cohorts(self):
        two_hours_ago = timezone.now() - timedelta(hours=2)
        stuck = Cohort.objects.create(team=self.team, name="Stuck", is_calculating=True, last_calculation=two_hours_ago)
        Cohort.objects.create(team=self.team, name="Fresh", is_calculating=True, last_calculation=timezone.now())
        Cohort.objects.create(
            team=self.team, name="Static", is_static=True, is_calculating=True, last_calculation=two_hours_ago
        )
        Cohort.objects.create(
            team=self.team,
            name="Deleted",
            deleted=True,
            is_calculating=True,
            last_calculation=two_hours_ago,
        )

        response = self.client.get("/api/cohorts_staff/stuck/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual([result["id"] for result in data["results"]], [stuck.id])
        self.assertEqual(data["total_count"], 1)

    @patch("posthog.tasks.calculate_cohort.calculate_cohort_ch.delay")
    def test_recalculate_bumps_version_and_enqueues_with_initiating_user(self, mock_delay):
        cohort = self._create_cross_org_cohort(is_calculating=True, pending_version=7)

        response = self.client.post("/api/cohorts_staff/recalculate/", {"cohort_ids": [cohort.id, 999999999]})
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)

        data = response.json()
        self.assertEqual(data["queued_cohort_ids"], [cohort.id])
        self.assertEqual(data["skipped"], [])
        self.assertEqual(data["not_found_cohort_ids"], [999999999])

        cohort.refresh_from_db()
        self.assertEqual(cohort.pending_version, 8)
        self.assertTrue(cohort.is_calculating)
        mock_delay.assert_called_once_with(cohort.id, 8, self.user.id)

    @parameterized.expand(
        [
            ("static", {"is_static": True}, "Static cohorts"),
            ("deleted", {"deleted": True}, "deleted"),
        ]
    )
    @patch("posthog.tasks.calculate_cohort.calculate_cohort_ch.delay")
    def test_recalculate_skips_with_reason_and_does_not_enqueue(
        self, _name, cohort_kwargs, reason_fragment, mock_delay
    ):
        cohort = Cohort.objects.create(team=self.team, name="Skipped", **cohort_kwargs)

        response = self.client.post("/api/cohorts_staff/recalculate/", {"cohort_ids": [cohort.id]})
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)

        data = response.json()
        self.assertEqual(data["queued_cohort_ids"], [])
        (skipped,) = data["skipped"]
        self.assertEqual(skipped["cohort_id"], cohort.id)
        self.assertIn(reason_fragment, skipped["reason"])
        mock_delay.assert_not_called()

    def test_recalculate_rejects_more_than_max_cohorts(self):
        response = self.client.post("/api/cohorts_staff/recalculate/", {"cohort_ids": list(range(1, 12))})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("products.cohorts.backend.api.staff_tools.increment_version_and_enqueue_calculate_cohort")
    def test_recalculate_reports_partial_when_dependency_resolution_falls_back(self, mock_increment):
        # increment_version_and_enqueue_calculate_cohort returns False when it fell back to
        # enqueueing just this cohort because resolving its dependency chain failed. The
        # cohort is still queued, but the operator needs to know the dependency chain was skipped.
        mock_increment.return_value = False
        cohort = Cohort.objects.create(team=self.team, name="Cohort", pending_version=1)

        response = self.client.post("/api/cohorts_staff/recalculate/", {"cohort_ids": [cohort.id]})
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)

        data = response.json()
        self.assertEqual(data["queued_cohort_ids"], [cohort.id])
        self.assertEqual(data["partial_cohort_ids"], [cohort.id])

    @patch("products.cohorts.backend.api.staff_tools.increment_version_and_enqueue_calculate_cohort")
    def test_recalculate_continues_batch_and_reports_failure_when_one_cohort_errors(self, mock_increment):
        # A raise for one cohort must not 500 the whole request: earlier cohorts in the batch
        # already had their version bumped and task enqueued, so losing that in a 500 would make
        # a caller retry the full batch and double-enqueue them.
        cohort_ok = Cohort.objects.create(team=self.team, name="Ok", pending_version=1)
        cohort_bad = Cohort.objects.create(team=self.team, name="Bad", pending_version=1)

        def side_effect(cohort, *, initiating_user):
            if cohort.id == cohort_bad.id:
                raise RuntimeError("boom")
            return True

        mock_increment.side_effect = side_effect

        response = self.client.post("/api/cohorts_staff/recalculate/", {"cohort_ids": [cohort_ok.id, cohort_bad.id]})
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)

        data = response.json()
        self.assertEqual(data["queued_cohort_ids"], [cohort_ok.id])
        (failed,) = data["failed_cohort_ids"]
        self.assertEqual(failed["cohort_id"], cohort_bad.id)
        self.assertIn("boom", failed["error"])
