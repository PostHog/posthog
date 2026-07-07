from posthog.test.base import ClickhouseTestMixin, NonAtomicBaseTest

from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized

from posthog.schema import AccountsQuery, AccountsQueryResponse

from posthog.hogql.errors import ExposedHogQLError

from posthog.api.tagged_item import set_tags_on_object
from posthog.constants import AvailableFeature
from posthog.models import Tag, User
from posthog.models.team import Team
from posthog.rbac.user_access_control import UserAccessControlError

from products.customer_analytics.backend.hogql_queries.accounts_query_runner import AccountsQueryRunner
from products.customer_analytics.backend.logic import relationships as relationships_logic
from products.customer_analytics.backend.models import AccountRelationshipDefinition, CustomPropertyValue
from products.customer_analytics.backend.test.factories import create_account, create_custom_property_definition
from products.notebooks.backend.models import Notebook, ResourceNotebook

try:
    from ee.models.rbac.access_control import AccessControl
except ImportError:
    pass


@override_settings(IN_UNIT_TESTING=True)
class TestAccountsQueryRunner(ClickhouseTestMixin, NonAtomicBaseTest):
    def _run_query(self, user: User | None = None, **query_kwargs) -> tuple[AccountsQueryRunner, AccountsQueryResponse]:
        runner = AccountsQueryRunner(
            query=AccountsQuery(**query_kwargs), team=self.team, user=user if user is not None else self.user
        )
        return runner, runner.calculate()

    def _ids(self, user: User | None = None, **query_kwargs) -> list[str]:
        runner, response = self._run_query(user=user, **query_kwargs)
        name_idx = runner.columns.index("name")
        return [row[name_idx]["id"] for row in response.results]

    def _names(self, **query_kwargs) -> list[str]:
        runner, response = self._run_query(**query_kwargs)
        name_idx = runner.columns.index("name")
        return [row[name_idx]["name"] for row in response.results]

    def test_team_isolation(self):
        mine_1 = create_account(team_id=self.team.id, name="Mine 1")
        mine_2 = create_account(team_id=self.team.id, name="Mine 2")

        other_team = Team.objects.create(organization=self.organization)
        create_account(team_id=other_team.id, name="Theirs")

        self.assertEqual(set(self._ids()), {str(mine_1.id), str(mine_2.id)})

    def test_default_ordering_is_created_at_desc(self):
        with timezone.override("UTC"):
            older = create_account(team_id=self.team.id, name="Older")
            newer = create_account(team_id=self.team.id, name="Newer")
        self.assertEqual(self._ids(), [str(newer.id), str(older.id)])

    @parameterized.expand(
        [
            ("name_exact", "Acme Corp", ["Acme Corp"]),
            ("name_partial_case_insensitive", "acme", ["Acme Corp"]),
            ("external_id_partial", "glx-9", ["Globex"]),
            ("matches_name_or_external_id", "1", ["Acme Corp"]),
            ("no_match", "zzzz", []),
        ]
    )
    def test_search(self, _name, search, expected_names):
        create_account(team_id=self.team.id, name="Acme Corp", external_id="acme-1")
        create_account(team_id=self.team.id, name="Globex", external_id="glx-99")

        self.assertEqual(sorted(self._names(search=search)), sorted(expected_names))

    def test_blank_search_returns_all(self):
        create_account(team_id=self.team.id, name="A")
        create_account(team_id=self.team.id, name="B")
        self.assertEqual(len(self._ids(search="")), 2)
        self.assertEqual(len(self._ids(search="   ")), 2)

    def test_search_respects_team_isolation(self):
        other_team = Team.objects.create(organization=self.organization)
        create_account(team_id=other_team.id, name="Acme")
        create_account(team_id=self.team.id, name="Acme")
        self.assertEqual(len(self._ids(search="acme")), 1)

    def test_tags_filter_or_semantics(self):
        billing_tag = Tag.objects.create(name="billing", team=self.team)
        urgent_tag = Tag.objects.create(name="urgent", team=self.team)
        churn_tag = Tag.objects.create(name="churn", team=self.team)

        billing = create_account(team_id=self.team.id, name="Billing Co")
        billing.tagged_items.create(tag=billing_tag)
        urgent = create_account(team_id=self.team.id, name="Urgent Co")
        urgent.tagged_items.create(tag=urgent_tag)
        churn = create_account(team_id=self.team.id, name="Churn Co")
        churn.tagged_items.create(tag=churn_tag)
        create_account(team_id=self.team.id, name="Untagged Co")

        self.assertEqual(set(self._ids(tagNames=["billing", "urgent"])), {str(billing.id), str(urgent.id)})

    def test_tags_filter_deduplicates_multi_match(self):
        billing_tag = Tag.objects.create(name="billing", team=self.team)
        urgent_tag = Tag.objects.create(name="urgent", team=self.team)
        churn_tag = Tag.objects.create(name="churn", team=self.team)

        both_tags = create_account(team_id=self.team.id, name="Both Tagged")
        both_tags.tagged_items.create(tag=billing_tag)
        both_tags.tagged_items.create(tag=urgent_tag)

        billing_only = create_account(team_id=self.team.id, name="Billing Only")
        billing_only.tagged_items.create(tag=billing_tag)

        other_tag_account = create_account(team_id=self.team.id, name="Churn Only")
        other_tag_account.tagged_items.create(tag=churn_tag)

        create_account(team_id=self.team.id, name="Untagged")

        ids = self._ids(tagNames=["billing", "urgent"])
        self.assertEqual(sorted(ids), sorted([str(both_tags.id), str(billing_only.id)]))
        # both_tags must appear exactly once even though it matches via two tagged_items rows.
        self.assertEqual(ids.count(str(both_tags.id)), 1)

    def test_tags_empty_list_returns_all(self):
        a = create_account(team_id=self.team.id, name="A")
        b = create_account(team_id=self.team.id, name="B")
        tagged = create_account(team_id=self.team.id, name="Tagged")
        tagged.tagged_items.create(tag=Tag.objects.create(name="some_tag", team=self.team))

        self.assertEqual(set(self._ids(tagNames=[])), {str(a.id), str(b.id), str(tagged.id)})

    def test_tags_filter_respects_team_isolation_via_tag_table(self):
        other_team = Team.objects.create(organization=self.organization)
        other_tag = Tag.objects.create(name="billing", team=other_team)
        other_account = create_account(team_id=other_team.id, name="Other")
        other_account.tagged_items.create(tag=other_tag)

        local_tag = Tag.objects.create(name="billing", team=self.team)
        local_account = create_account(team_id=self.team.id, name="Mine")
        local_account.tagged_items.create(tag=local_tag)

        self.assertEqual(self._ids(tagNames=["billing"]), [str(local_account.id)])

    def _assign(self, account, user, definition_name="CSM"):
        definition, _ = AccountRelationshipDefinition.objects.for_team(self.team.id).get_or_create(
            team_id=self.team.id, name=definition_name
        )
        return relationships_logic.assign(
            team_id=self.team.id, account=account, definition=definition, user=user, created_by=user
        )

    def test_all_roles_unassigned(self):
        holder = self._create_user("holder@x.com")
        assigned = create_account(team_id=self.team.id, name="Assigned")
        self._assign(assigned, holder)
        previously_assigned = create_account(team_id=self.team.id, name="Previously assigned")
        rel = self._assign(previously_assigned, holder)
        relationships_logic.end_relationship(
            team_id=self.team.id, account_id=str(previously_assigned.id), relationship_id=str(rel.id)
        )
        never_assigned = create_account(team_id=self.team.id, name="Never assigned")

        self.assertEqual(set(self._ids(allRolesUnassigned=True)), {str(previously_assigned.id), str(never_assigned.id)})

    def test_combined_assigned_to_and_tags(self):
        enterprise_tag = Tag.objects.create(name="enterprise", team=self.team)
        startup_tag = Tag.objects.create(name="startup", team=self.team)
        holder = self._create_user("holder@x.com")
        other_holder = self._create_user("other-holder@x.com")

        match = create_account(team_id=self.team.id, name="A")
        self._assign(match, holder)
        match.tagged_items.create(tag=enterprise_tag)

        wrong_tag = create_account(team_id=self.team.id, name="B")
        self._assign(wrong_tag, holder)
        wrong_tag.tagged_items.create(tag=startup_tag)

        wrong_user = create_account(team_id=self.team.id, name="C")
        self._assign(wrong_user, other_holder)
        wrong_user.tagged_items.create(tag=enterprise_tag)

        self.assertEqual(self._ids(assignedToUserIds=[holder.id], tagNames=["enterprise"]), [str(match.id)])

    @parameterized.expand(
        [
            ("seeded_csm", "CSM"),
            ("seeded_account_owner", "Account owner"),
            ("custom_definition", "Onboarding manager"),
        ]
    )
    def test_assigned_to_user_matches_any_actively_held_relationship(self, _name, definition_name):
        holder = self._create_user("holder@x.com")
        other_holder = self._create_user("other-holder@x.com")
        mine = create_account(team_id=self.team.id, name="Mine")
        self._assign(mine, holder, definition_name)
        someone_elses = create_account(team_id=self.team.id, name="Someone else's")
        self._assign(someone_elses, other_holder, definition_name)
        self.assertEqual(self._ids(assignedToUserIds=[holder.id]), [str(mine.id)])

    def test_assigned_to_user_excludes_ended_assignments(self):
        holder = self._create_user("holder@x.com")
        account = create_account(team_id=self.team.id, name="Handed off")
        rel = self._assign(account, holder)
        relationships_logic.end_relationship(
            team_id=self.team.id, account_id=str(account.id), relationship_id=str(rel.id)
        )
        self.assertEqual(self._ids(assignedToUserIds=[holder.id]), [])

    def test_assigned_to_user_matches_any_of_multiple_ids(self):
        holder_a = self._create_user("a@x.com")
        holder_b = self._create_user("b@x.com")
        holder_c = self._create_user("c@x.com")
        as_csm = create_account(team_id=self.team.id, name="CSM A")
        self._assign(as_csm, holder_a)
        as_ae = create_account(team_id=self.team.id, name="AE B")
        self._assign(as_ae, holder_b, "Account executive")
        other = create_account(team_id=self.team.id, name="CSM C")
        self._assign(other, holder_c)
        self.assertEqual(set(self._ids(assignedToUserIds=[holder_a.id, holder_b.id])), {str(as_csm.id), str(as_ae.id)})

    def test_assigned_to_user_is_independent_of_requesting_user(self):
        # The ids are explicit, not the requester — a shared "my accounts" link
        # resolves to the same accounts no matter which user opens it.
        holder = self._create_user("holder@x.com")
        other_holder = self._create_user("other-holder@x.com")
        target = create_account(team_id=self.team.id, name="Target")
        self._assign(target, holder)
        other = create_account(team_id=self.team.id, name="Other")
        self._assign(other, other_holder)
        other_user = self._create_user("other@example.com")
        as_user = self._ids(user=self.user, assignedToUserIds=[holder.id])
        as_other_user = self._ids(user=other_user, assignedToUserIds=[holder.id])
        self.assertEqual(as_user, [str(target.id)])
        self.assertEqual(as_user, as_other_user)

    def test_assigned_to_user_unknown_id_matches_nothing(self):
        account = create_account(team_id=self.team.id, name="Has CSM")
        self._assign(account, self._create_user("holder@x.com"))
        self.assertEqual(self._ids(assignedToUserIds=[999999]), [])

    def test_assigned_to_user_empty_ids_is_a_noop(self):
        a = create_account(team_id=self.team.id, name="Has CSM")
        self._assign(a, self._create_user("holder@x.com"))
        self.assertEqual(self._ids(assignedToUserIds=[]), [str(a.id)])

    def test_assigned_to_user_combines_with_search(self):
        holder = self._create_user("holder@x.com")
        match = create_account(team_id=self.team.id, name="Acme")
        self._assign(match, holder)
        globex = create_account(team_id=self.team.id, name="Globex")
        self._assign(globex, holder)
        self.assertEqual(self._ids(assignedToUserIds=[holder.id], search="acme"), [str(match.id)])

    def test_assigned_to_user_respects_team_isolation(self):
        holder = self._create_user("holder@x.com")
        other_team = Team.objects.create(organization=self.organization)
        theirs = create_account(team_id=other_team.id, name="Theirs")
        their_definition = AccountRelationshipDefinition.objects.for_team(other_team.id).create(
            team_id=other_team.id, name="CSM"
        )
        relationships_logic.assign(
            team_id=other_team.id, account=theirs, definition=their_definition, user=holder, created_by=holder
        )
        mine = create_account(team_id=self.team.id, name="Mine")
        self._assign(mine, holder)
        self.assertEqual(self._ids(assignedToUserIds=[holder.id]), [str(mine.id)])

    def test_assigned_to_user_metrics_mode_counts_only_matching_accounts(self):
        holder = self._create_user("holder@x.com")
        other_holder = self._create_user("other-holder@x.com")
        mine = create_account(team_id=self.team.id, name="Mine")
        self._assign(mine, holder)
        theirs = create_account(team_id=self.team.id, name="Theirs")
        self._assign(theirs, other_holder)
        runner = AccountsQueryRunner(
            query=AccountsQuery(metrics=["count()"], select=[], assignedToUserIds=[holder.id]),
            team=self.team,
            user=self.user,
        )
        response = runner.calculate()
        self.assertEqual(response.metricsResults, [1])

    def test_assigned_to_user_id_is_part_of_the_cache_key(self):
        # Regression: "my accounts" must not collide in the query cache across users.
        # The user id that selects the accounts rides in the query (assignedToUserIds),
        # so it lands in get_cache_payload()["query"] and therefore in get_cache_key().
        # (Pre-fix, the boolean assignedToCurrentUser was identical across users while
        # the results differed by the server-resolved self.user.id, so one user's cached
        # accounts could be served to another.)
        runner_a = AccountsQueryRunner(query=AccountsQuery(assignedToUserIds=[1]), team=self.team, user=self.user)
        runner_b = AccountsQueryRunner(query=AccountsQuery(assignedToUserIds=[2]), team=self.team, user=self.user)
        self.assertEqual(runner_a.get_cache_payload()["query"]["assignedToUserIds"], [1])
        self.assertNotEqual(runner_a.get_cache_key(), runner_b.get_cache_key())

    def test_ordering_by_name_asc(self):
        banana = create_account(team_id=self.team.id, name="Banana")
        apple = create_account(team_id=self.team.id, name="Apple")
        self.assertEqual(self._ids(orderBy=["name"]), [str(apple.id), str(banana.id)])

    def test_ordering_by_name_desc(self):
        apple = create_account(team_id=self.team.id, name="Apple")
        banana = create_account(team_id=self.team.id, name="Banana")
        self.assertEqual(self._ids(orderBy=["-name"]), [str(banana.id), str(apple.id)])

    def _link_notebooks(self, account, count: int) -> None:
        for i in range(count):
            notebook = Notebook.objects.create(
                team=self.team,
                title=f"NB {account.name} {i}",
                content=[],
                visibility=Notebook.Visibility.INTERNAL,
            )
            ResourceNotebook.objects.create(notebook=notebook, account=account)

    def test_ordering_by_notebook_count_asc(self):
        zero = create_account(team_id=self.team.id, name="Zero")
        one = create_account(team_id=self.team.id, name="One")
        two = create_account(team_id=self.team.id, name="Two")
        self._link_notebooks(one, 1)
        self._link_notebooks(two, 2)

        runner = AccountsQueryRunner(
            query=AccountsQuery(
                select=["id", "accounts.notebooks.count AS notebook_count"],
                orderBy=["notebook_count", "name"],
            ),
            team=self.team,
            user=self.user,
        )
        response = runner.calculate()
        id_idx = runner.columns.index("id")
        # Accounts with no notebook rows aggregate to NULL (no group), so they appear before
        # the rows with positive counts when sorting ASC. Tie-break by name keeps it deterministic.
        self.assertEqual(
            [str(row[id_idx]) for row in response.results],
            [str(zero.id), str(one.id), str(two.id)],
        )

    def test_ordering_by_notebook_count_desc(self):
        zero = create_account(team_id=self.team.id, name="Zero")
        one = create_account(team_id=self.team.id, name="One")
        two = create_account(team_id=self.team.id, name="Two")
        self._link_notebooks(one, 1)
        self._link_notebooks(two, 2)

        runner = AccountsQueryRunner(
            query=AccountsQuery(
                select=["id", "accounts.notebooks.count AS notebook_count"],
                orderBy=["notebook_count DESC", "name"],
            ),
            team=self.team,
            user=self.user,
        )
        response = runner.calculate()
        id_idx = runner.columns.index("id")
        self.assertEqual(
            [str(row[id_idx]) for row in response.results[:2]],
            [str(two.id), str(one.id)],
        )
        # `zero` has no notebook rows, so the aggregate is NULL and lands at the end.
        self.assertEqual(str(response.results[-1][id_idx]), str(zero.id))

    def test_pagination_limit_and_offset(self):
        ids = [str(create_account(team_id=self.team.id, name=f"Account {i:02d}").id) for i in range(5)]
        expected_reverse = list(reversed(ids))

        page_one_runner, page_one_response = self._run_query(limit=2, offset=0)
        name_idx = page_one_runner.columns.index("name")
        self.assertEqual([row[name_idx]["id"] for row in page_one_response.results], expected_reverse[:2])
        self.assertTrue(page_one_response.hasMore)

        page_three_runner, page_three_response = self._run_query(limit=2, offset=4)
        name_idx = page_three_runner.columns.index("name")
        self.assertEqual([row[name_idx]["id"] for row in page_three_response.results], expected_reverse[4:])
        self.assertFalse(page_three_response.hasMore)

    def test_empty_result_set(self):
        create_account(team_id=self.team.id, name="Acme")
        _, response = self._run_query(search="nonexistent_substring_xyz")
        self.assertEqual(response.results, [])
        self.assertFalse(response.hasMore)
        self.assertEqual(response.offset, 0)

    def test_name_column_carries_id_external_id_and_display_name(self):
        account = create_account(team_id=self.team.id, name="A", external_id="ext-A")
        runner, response = self._run_query()
        name_idx = runner.columns.index("name")
        self.assertEqual(
            response.results[0][name_idx],
            {"name": "A", "external_id": "ext-A", "id": str(account.id)},
        )

    def test_name_column_is_prepended_when_not_in_select(self):
        runner = AccountsQueryRunner(query=AccountsQuery(select=["external_id"]), team=self.team)
        self.assertEqual(runner.columns, ["name", "external_id"])

    def test_set_tags_on_object_helper_matches(self):
        # Mirror existing API test setup that uses set_tags_on_object.
        account = create_account(team_id=self.team.id, name="A")
        set_tags_on_object(["enterprise"], account)
        self.assertEqual(self._ids(tagNames=["enterprise"]), [str(account.id)])

    def test_custom_select_uses_only_requested_columns(self):
        create_account(team_id=self.team.id, name="A")
        runner = AccountsQueryRunner(query=AccountsQuery(select=["id", "name"]), team=self.team, user=self.user)
        response = runner.calculate()
        self.assertEqual(runner.columns, ["id", "name"])
        self.assertEqual(len(response.results[0]), 2)

    def test_custom_select_deduplicates(self):
        create_account(team_id=self.team.id, name="A")
        runner = AccountsQueryRunner(query=AccountsQuery(select=["id", "name", "id"]), team=self.team)
        self.assertEqual(runner.columns, ["id", "name"])

    def test_metrics_mode_returns_aggregations_and_no_rows(self):
        create_account(team_id=self.team.id, name="A")
        create_account(team_id=self.team.id, name="B")
        create_account(team_id=self.team.id, name="C")
        _, response = self._run_query(metrics=["count()"], select=[])
        self.assertEqual(response.results, [])
        self.assertEqual(response.columns, [])
        self.assertEqual(response.metricsResults, [3])

    def test_combined_mode_returns_rows_and_metrics_in_one_response(self):
        create_account(team_id=self.team.id, name="A")
        create_account(team_id=self.team.id, name="B")
        create_account(team_id=self.team.id, name="C")
        runner, response = self._run_query(select=["name"], metrics=["count()"])
        name_idx = runner.columns.index("name")
        self.assertEqual(len(response.results), 3)
        self.assertTrue(all(row[name_idx]["name"] for row in response.results))
        self.assertEqual(response.metricsResults, [3])

    def test_metrics_mode_reuses_table_where_clause(self):
        create_account(team_id=self.team.id, name="Acme")
        create_account(team_id=self.team.id, name="Other")
        _, response = self._run_query(metrics=["count()"], select=[], search="acme")
        self.assertEqual(response.metricsResults, [1])

    def test_metrics_mode_respects_team_isolation(self):
        create_account(team_id=self.team.id, name="Mine")
        other_team = Team.objects.create(organization=self.organization)
        create_account(team_id=other_team.id, name="Theirs")
        _, response = self._run_query(metrics=["count()"], select=[])
        self.assertEqual(response.metricsResults, [1])

    def test_bad_metric_raises_an_error_naming_the_offending_expression(self):
        create_account(team_id=self.team.id, name="A")
        with self.assertRaises(ExposedHogQLError) as ctx:
            self._run_query(select=["name"], metrics=["count()", "sum(does_not_exist)"])
        message = str(ctx.exception)
        self.assertIn("sum(does_not_exist)", message)
        # The healthy metric should not be blamed.
        self.assertNotIn("`count()`", message)

    def test_filter_expression_narrows_the_row_set(self):
        create_account(team_id=self.team.id, name="A", _properties={"score": 80})
        create_account(team_id=self.team.id, name="B", _properties={"score": 20})
        create_account(team_id=self.team.id, name="C", _properties={"score": 10})
        ids = self._ids(filterExpression="JSONExtract(properties, 'score', 'Nullable(Int64)') < 50")
        self.assertEqual(len(ids), 2)

    def test_filter_expression_combines_with_search(self):
        create_account(team_id=self.team.id, name="Match", _properties={"score": 5})
        create_account(team_id=self.team.id, name="WrongScore", _properties={"score": 99})
        create_account(team_id=self.team.id, name="WrongName", _properties={"score": 5})
        names = self._names(
            search="match",
            filterExpression="JSONExtract(properties, 'score', 'Nullable(Int64)') < 50",
        )
        self.assertEqual(names, ["Match"])

    def test_custom_property_value_round_trips_through_a_selected_alias(self):
        account = create_account(team_id=self.team.id, name="A")
        definition = create_custom_property_definition(team_id=self.team.id, name="Plan")
        CustomPropertyValue.objects.unscoped().create(
            team_id=self.team.id, account=account, definition=definition, value_str="enterprise"
        )
        other = create_account(team_id=self.team.id, name="No value")

        runner = AccountsQueryRunner(
            query=AccountsQuery(select=["id", f"accounts.custom_properties.values.`{definition.id}` AS cp_x"]),
            team=self.team,
            user=self.user,
        )
        response = runner.calculate()
        id_idx, value_idx = runner.columns.index("id"), runner.columns.index("cp_x")
        values_by_id = {str(row[id_idx]): row[value_idx] for row in response.results}

        self.assertEqual(values_by_id[str(account.id)], "enterprise")
        # An account with no value for the definition aggregates to NULL/empty.
        self.assertFalse(values_by_id[str(other.id)])

    def test_numeric_custom_property_aggregates_in_metrics_mode(self):
        # Overview tiles sum/avg a numeric custom property by casting its (string) value to a float.
        definition = create_custom_property_definition(team_id=self.team.id, name="Seats", display_type="number")
        for account_name, seats in [("A", 10.0), ("B", 30.0)]:
            account = create_account(team_id=self.team.id, name=account_name)
            CustomPropertyValue.objects.unscoped().create(
                team_id=self.team.id, account=account, definition=definition, value_num=seats
            )
        create_account(team_id=self.team.id, name="No value")

        expr = f"toFloatOrNull(accounts.custom_properties.values.`{definition.id}`)"
        runner = AccountsQueryRunner(
            query=AccountsQuery(metrics=[f"sum({expr})", f"avg({expr})"], select=[]),
            team=self.team,
            user=self.user,
        )
        response = runner.calculate()
        # Sum ignores the null (no-value) account; avg averages only the two present values.
        self.assertEqual(response.metricsResults, [40.0, 20.0])

    def test_validate_query_runner_access_default(self):
        runner = AccountsQueryRunner(query=AccountsQuery(), team=self.team)
        self.assertTrue(runner.validate_query_runner_access(self.user))

    def test_validate_query_runner_access_denied(self):
        AccessControl.objects.create(team=self.team, resource="customer_analytics", access_level="none")
        self.organization.available_product_features.append({"key": AvailableFeature.ACCESS_CONTROL})  # type: ignore[union-attr]
        self.organization.save()

        runner = AccountsQueryRunner(query=AccountsQuery(), team=self.team)
        self.assertRaises(UserAccessControlError, runner.validate_query_runner_access, self.user)
