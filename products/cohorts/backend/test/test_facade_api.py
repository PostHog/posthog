from uuid import uuid4

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.team import Team

from products.cohorts.backend.facade.api import CohortInsertFailed, add_persons_to_static_cohort, cohort_exists_for_team
from products.cohorts.backend.models.cohort import Cohort


class TestCohortExistsForTeam(BaseTest):
    def test_a_cohort_is_only_visible_to_its_own_team(self) -> None:
        cohort = Cohort.objects.create(team=self.team, name="Churn risk")
        other_team = Team.objects.create(organization=self.organization, name="Other")

        assert cohort_exists_for_team(team_id=self.team.id, cohort_id=cohort.id)
        assert not cohort_exists_for_team(team_id=other_team.id, cohort_id=cohort.id)

    def test_a_soft_deleted_cohort_still_counts(self) -> None:
        cohort = Cohort.objects.create(team=self.team, name="Churn risk", deleted=True)

        assert cohort_exists_for_team(team_id=self.team.id, cohort_id=cohort.id)


class TestAddPersonsToStaticCohort(BaseTest):
    def test_a_failed_insert_raises_and_logs_no_activity(self) -> None:
        cohort = Cohort.objects.create(team=self.team, name="Beta testers", is_static=True, created_by=self.user)
        person_uuid = str(uuid4())

        with (
            patch(
                "products.cohorts.backend.facade.api.validate_person_uuids_exist",
                return_value=[person_uuid],
            ),
            patch.object(Cohort, "_insert_batch_via_personhog", side_effect=RuntimeError("personhog down")),
            pytest.raises(CohortInsertFailed),
        ):
            add_persons_to_static_cohort(
                team_id=self.team.id, user_id=self.user.id, cohort_id=cohort.id, person_ids=[person_uuid]
            )

        cohort.refresh_from_db()
        assert cohort.errors_calculating == 1
        assert cohort.last_error_at is not None
        assert not cohort.is_calculating
        assert not ActivityLog.objects.filter(scope="Cohort", item_id=str(cohort.id)).exists()
