from posthog.test.base import BaseTest

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import Table
from posthog.hogql.database.schema.system import SystemTables
from posthog.hogql.printer import print_prepared_ast
from posthog.hogql.printer.access_control import filter_to_expr

from posthog.models import Team, User
from posthog.models.access_filter import apply_filter, filter_q

from products.authz.backend.facade.contracts import ResourceIds
from products.feature_flags.backend.models.feature_flag import FeatureFlag


class TestQuerysetAccessFilter(BaseTest):
    @parameterized.expand(
        [
            ("only", False, True, False),
            ("except", True, True, False),
            ("creator_only", False, True, True),
            ("creator_except", True, True, True),
            ("capped", False, False, True),
        ]
    )
    def test_queryset_and_single_object_decisions_agree(
        self, _name: str, excluded: bool, complete: bool, creator_exempt: bool
    ) -> None:
        other = User.objects.create_and_join(self.organization, "other@example.com", "test-password")
        flags = [
            FeatureFlag.objects.create(team=self.team, key="first", created_by=other),
            FeatureFlag.objects.create(team=self.team, key="own", created_by=self.user),
            FeatureFlag.objects.create(team=self.team, key="no-creator", created_by=None),
        ]
        other_team = Team.objects.create(organization=self.organization, name="Other project")
        FeatureFlag.objects.create(team=other_team, key="other-project", created_by=self.user)
        result = ResourceIds(
            ids=frozenset({str(flags[0].pk)}) if complete else frozenset(),
            excluded=excluded,
            complete=complete,
            creator_exempt=creator_exempt,
        )
        expected = [
            flag.pk
            for flag in flags
            if result.allows(str(flag.pk), created_by_user_id=flag.created_by_id, subject_user_id=self.user.pk)
        ]
        queryset = FeatureFlag.objects.filter(team=self.team).order_by("id")
        assert (
            list(apply_filter(queryset, result, subject_user_id=self.user.pk).values_list("id", flat=True)) == expected
        )
        assert (
            list(queryset.filter(filter_q(result, subject_user_id=self.user.pk)).values_list("id", flat=True))
            == expected
        )
        assert (
            list(apply_filter(queryset, result, subject_user_id=self.user.pk).values_list("id", flat=True)[:1])
            == expected[:1]
        )


class TestHogQLAccessFilter(SimpleTestCase):
    @parameterized.expand([("only", False, "in("), ("except", True, "notin(")])
    def test_filter_uses_the_resource_id_and_null_safe_creator(self, _name: str, excluded: bool, operator: str) -> None:
        table = SystemTables().children["dashboards"].table
        assert isinstance(table, Table)
        table_type = ast.TableType(table=table)
        result = ResourceIds(ids=frozenset({"1"}), complete=True, excluded=excluded, creator_exempt=True)
        guard = filter_to_expr(result, "id", table_type, "created_by_id", 7)
        assert guard is not None
        sql = print_prepared_ast(guard, HogQLContext(team_id=1), dialect="hogql").lower()
        assert operator in sql
        assert "tostring(id)" in sql
        assert "ifnull" in sql and "created_by_id" in sql and "7" in sql

    def test_unrestricted_and_capped_results(self) -> None:
        table = SystemTables().children["dashboards"].table
        assert isinstance(table, Table)
        table_type = ast.TableType(table=table)
        assert (
            filter_to_expr(ResourceIds(ids=frozenset(), complete=True, excluded=True), "id", table_type, None, 1)
            is None
        )
        guard = filter_to_expr(
            ResourceIds(ids=frozenset(), complete=False, creator_exempt=True), "id", table_type, "created_by_id", 1
        )
        assert isinstance(guard, ast.Constant) and guard.value is False
