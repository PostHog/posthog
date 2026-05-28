from posthog.test.base import ClickhouseTestMixin, NonAtomicBaseTest

from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized

from posthog.schema import AccountsQuery, AccountsQueryResponse

from posthog.api.tagged_item import set_tags_on_object
from posthog.models import Tag
from posthog.models.team import Team

from products.customer_analytics.backend.hogql_queries.accounts_query_runner import AccountsQueryRunner
from products.customer_analytics.backend.test.factories import create_account
from products.notebooks.backend.models import Notebook, ResourceNotebook


@override_settings(IN_UNIT_TESTING=True)
class TestAccountsQueryRunner(ClickhouseTestMixin, NonAtomicBaseTest):
    def _run_query(self, **query_kwargs) -> tuple[AccountsQueryRunner, AccountsQueryResponse]:
        runner = AccountsQueryRunner(query=AccountsQuery(**query_kwargs), team=self.team)
        return runner, runner.calculate()

    def _ids(self, **query_kwargs) -> list[str]:
        runner, response = self._run_query(**query_kwargs)
        id_index = runner.columns.index("id")
        return [str(row[id_index]) for row in response.results]

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

        runner, response = self._run_query(search=search)
        name_idx = runner.columns.index("name")
        self.assertEqual(sorted(r[name_idx] for r in response.results), sorted(expected_names))

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

    def test_csm_filter_by_id(self):
        match = create_account(team_id=self.team.id, name="Has CSM", _properties={"csm": {"id": 7, "email": "a@x.com"}})
        create_account(team_id=self.team.id, name="Other CSM", _properties={"csm": {"id": 9, "email": "b@x.com"}})
        self.assertEqual(self._ids(csm=7), [str(match.id)])

    @parameterized.expand(
        [
            ("absent_keys", {"_properties": {}}),
            ("null_valued_keys", {"properties": {}}),
        ]
    )
    def test_csm_unassigned_matches_missing_and_null(self, _name, unassigned_kwargs):
        create_account(team_id=self.team.id, name="Assigned", properties={"csm": {"id": 7, "email": "a@x.com"}})
        unassigned = create_account(team_id=self.team.id, name="Unassigned", **unassigned_kwargs)
        self.assertEqual(self._ids(csm="unassigned"), [str(unassigned.id)])

    def test_account_executive_filter_by_id(self):
        match = create_account(
            team_id=self.team.id, name="A", _properties={"account_executive": {"id": 7, "email": "a@x.com"}}
        )
        create_account(team_id=self.team.id, name="B")
        self.assertEqual(self._ids(accountExecutive=7), [str(match.id)])

    def test_account_owner_filter_by_id(self):
        match = create_account(
            team_id=self.team.id, name="A", _properties={"account_owner": {"id": 7, "email": "a@x.com"}}
        )
        create_account(team_id=self.team.id, name="B")
        self.assertEqual(self._ids(accountOwner=7), [str(match.id)])

    @parameterized.expand(
        [
            ("absent_keys", {"_properties": {}}),
            ("null_valued_keys", {"properties": {}}),
        ]
    )
    def test_all_roles_unassigned(self, _name, unassigned_kwargs):
        create_account(team_id=self.team.id, name="Has CSM", properties={"csm": {"id": 7, "email": "a@x.com"}})
        unassigned = create_account(team_id=self.team.id, name="Unassigned", **unassigned_kwargs)
        self.assertEqual(self._ids(allRolesUnassigned=True), [str(unassigned.id)])

    def test_combined_role_and_tags(self):
        enterprise_tag = Tag.objects.create(name="enterprise", team=self.team)
        startup_tag = Tag.objects.create(name="startup", team=self.team)

        match = create_account(team_id=self.team.id, name="A", _properties={"csm": {"id": 7, "email": "a@x.com"}})
        match.tagged_items.create(tag=enterprise_tag)

        wrong_tag = create_account(team_id=self.team.id, name="B", _properties={"csm": {"id": 7, "email": "a@x.com"}})
        wrong_tag.tagged_items.create(tag=startup_tag)

        wrong_csm = create_account(team_id=self.team.id, name="C", _properties={"csm": {"id": 8, "email": "c@x.com"}})
        wrong_csm.tagged_items.create(tag=enterprise_tag)

        self.assertEqual(self._ids(csm=7, tagNames=["enterprise"]), [str(match.id)])

    def test_role_filter_respects_team_isolation(self):
        other_team = Team.objects.create(organization=self.organization)
        create_account(team_id=other_team.id, name="Theirs", _properties={"csm": {"id": 7, "email": "a@x.com"}})
        mine = create_account(team_id=self.team.id, name="Mine", _properties={"csm": {"id": 7, "email": "a@x.com"}})
        self.assertEqual(self._ids(csm=7), [str(mine.id)])

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
        )
        response = runner.calculate()
        id_idx = runner.columns.index("id")
        self.assertEqual(
            [str(row[id_idx]) for row in response.results[:2]],
            [str(two.id), str(one.id)],
        )
        # `zero` has no notebook rows, so the aggregate is NULL and lands at the end.
        self.assertEqual(str(response.results[-1][id_idx]), str(zero.id))

    @parameterized.expand(
        [
            ("csm", "csm"),
            ("account_executive", "account_executive"),
        ]
    )
    def test_ordering_by_role_email_asc(self, _name, role_key):
        zed = create_account(
            team_id=self.team.id, name="Zed", _properties={role_key: {"id": 1, "email": "zed@example.com"}}
        )
        adam = create_account(
            team_id=self.team.id, name="Adam", _properties={role_key: {"id": 2, "email": "adam@example.com"}}
        )
        molly = create_account(
            team_id=self.team.id, name="Molly", _properties={role_key: {"id": 3, "email": "molly@example.com"}}
        )

        runner = AccountsQueryRunner(
            query=AccountsQuery(
                select=["id", role_key],
                orderBy=[f"tupleElement({role_key}, 2)"],
            ),
            team=self.team,
        )
        response = runner.calculate()
        id_idx = runner.columns.index("id")
        self.assertEqual(
            [str(row[id_idx]) for row in response.results],
            [str(adam.id), str(molly.id), str(zed.id)],
        )

    @parameterized.expand(
        [
            ("csm", "csm"),
            ("account_executive", "account_executive"),
        ]
    )
    def test_ordering_by_role_email_desc(self, _name, role_key):
        zed = create_account(
            team_id=self.team.id, name="Zed", _properties={role_key: {"id": 1, "email": "zed@example.com"}}
        )
        adam = create_account(
            team_id=self.team.id, name="Adam", _properties={role_key: {"id": 2, "email": "adam@example.com"}}
        )

        runner = AccountsQueryRunner(
            query=AccountsQuery(
                select=["id", role_key],
                orderBy=[f"tupleElement({role_key}, 2) DESC"],
            ),
            team=self.team,
        )
        response = runner.calculate()
        id_idx = runner.columns.index("id")
        self.assertEqual(
            [str(row[id_idx]) for row in response.results],
            [str(zed.id), str(adam.id)],
        )

    def test_pagination_limit_and_offset(self):
        ids = [str(create_account(team_id=self.team.id, name=f"Account {i:02d}").id) for i in range(5)]
        expected_reverse = list(reversed(ids))

        page_one_runner, page_one_response = self._run_query(limit=2, offset=0)
        self.assertTrue(page_one_response.hasMore)
        id_idx = page_one_runner.columns.index("id")
        self.assertEqual(
            [str(row[id_idx]) for row in page_one_response.results],
            expected_reverse[:2],
        )

        page_three_runner, page_three_response = self._run_query(limit=2, offset=4)
        self.assertFalse(page_three_response.hasMore)
        id_idx = page_three_runner.columns.index("id")
        self.assertEqual(
            [str(row[id_idx]) for row in page_three_response.results],
            expected_reverse[4:],
        )

    def test_empty_result_set(self):
        create_account(team_id=self.team.id, name="Acme")
        _, response = self._run_query(search="nonexistent_substring_xyz")
        self.assertEqual(response.results, [])
        self.assertFalse(response.hasMore)
        self.assertEqual(response.offset, 0)

    def test_external_id_is_in_default_columns(self):
        create_account(team_id=self.team.id, name="A", external_id="ext-A")
        runner = AccountsQueryRunner(query=AccountsQuery(), team=self.team)
        self.assertIn("external_id", runner.columns)

    def test_set_tags_on_object_helper_matches(self):
        # Mirror existing API test setup that uses set_tags_on_object.
        account = create_account(team_id=self.team.id, name="A", _properties={"csm": {"id": 7, "email": "a@x.com"}})
        set_tags_on_object(["enterprise"], account)
        self.assertEqual(self._ids(csm=7, tagNames=["enterprise"]), [str(account.id)])

    def test_custom_select_uses_only_requested_columns(self):
        create_account(team_id=self.team.id, name="A")
        runner = AccountsQueryRunner(query=AccountsQuery(select=["id", "name"]), team=self.team)
        response = runner.calculate()
        self.assertEqual(runner.columns, ["id", "name"])
        self.assertEqual(len(response.results[0]), 2)

    def test_custom_select_deduplicates(self):
        create_account(team_id=self.team.id, name="A")
        runner = AccountsQueryRunner(query=AccountsQuery(select=["id", "name", "id"]), team=self.team)
        self.assertEqual(runner.columns, ["id", "name"])
