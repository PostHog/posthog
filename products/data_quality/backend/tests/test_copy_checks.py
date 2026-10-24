from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.models.scoping import team_scope

from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.data_quality.backend.facade.api import copy_checks_to_saved_query, edit_check, upsert_check
from products.data_quality.backend.facade.enums import SubjectStatus, SubjectType
from products.data_quality.backend.logic.errors import CheckConfigError
from products.data_quality.backend.models import DataQualityCheck


class TestCopyEndpointChecks(BaseTest):
    @parameterized.expand([(True,), (False,)])
    def test_copy_preserves_checks_and_requires_review_for_removed_columns(self, enabled: bool) -> None:
        self.enterContext(team_scope(self.team.id))
        source = DataWarehouseSavedQuery.objects.create(
            team=self.team, name="published_v1", query={"query": "SELECT 1 AS old_column, 2 AS kept_column"}
        )
        target = DataWarehouseSavedQuery.objects.create(
            team=self.team, name="published_v2", query={"query": "SELECT 2 AS kept_column"}
        )
        for column in ["old_column", "kept_column"]:
            upsert_check(
                team=self.team,
                user=self.user,
                subject_type=SubjectType.VIEW,
                subject_uuid=str(source.id),
                check_type="not_null",
                column_name=column,
                config={},
                name=f"check_{column}",
                enabled=enabled,
            )
        assert copy_checks_to_saved_query(self.team.id, str(source.id), str(target.id)) == 2
        assert copy_checks_to_saved_query(self.team.id, str(source.id), str(target.id)) == 0
        copies = {
            check.column_name: check
            for check in DataQualityCheck.objects.for_team(self.team.id).filter(saved_query=target)
        }
        assert copies["old_column"].subject_status == SubjectStatus.NEEDS_REVIEW
        assert copies["kept_column"].subject_status == SubjectStatus.ACTIVE
        assert all(check.enabled == enabled and check.last_run_at is None for check in copies.values())
        assert (
            DataQualityCheck.objects.for_team(self.team.id)
            .filter(saved_query=source, subject_status=SubjectStatus.ACTIVE)
            .count()
            == 2
        )
        with self.assertRaises(CheckConfigError):
            edit_check(team=self.team, check=copies["old_column"], editor=self.user, column_name="still_missing")
        repaired = edit_check(
            team=self.team, check=copies["old_column"], editor=self.user, column_name="kept_column", check_type="unique"
        )
        assert repaired.subject_status == SubjectStatus.ACTIVE
        assert repaired.column_name == "kept_column"

    def test_named_checks_keep_a_readable_name_across_multiple_versions(self) -> None:
        source = DataWarehouseSavedQuery.objects.create(
            team=self.team, name="published_v1", query={"query": "SELECT 1 AS value"}
        )
        upsert_check(
            team=self.team,
            user=self.user,
            subject_type=SubjectType.VIEW,
            subject_uuid=str(source.id),
            check_type="not_null",
            column_name="value",
            config={},
            name="revenue_present",
        )
        for version in [2, 3]:
            target = DataWarehouseSavedQuery.objects.create(
                team=self.team, name=f"published_v{version}", query={"query": "SELECT 2 AS value"}
            )
            copy_checks_to_saved_query(self.team.id, str(source.id), str(target.id))
            check = DataQualityCheck.objects.for_team(self.team.id).get(saved_query=target)
            assert check.name == f"revenue_present__published_v{version}"
            source = target
