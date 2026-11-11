from datetime import UTC, datetime, timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock

from asgiref.sync import async_to_sync
from parameterized import parameterized

from posthog.models import Organization, Team

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.actions.backend.facade import api, contracts, testing
from products.actions.backend.facade.api import action_filter_conditions
from products.actions.backend.logic import saved_handlers
from products.actions.backend.models.action import Action


class TestActionFilterConditions(APIBaseTest):
    def _action(self, name: str, **kwargs) -> Action:
        kwargs.setdefault("steps_json", [{"event": "checkout completed"}])
        kwargs.setdefault("team", self.team)
        return Action.objects.create(name=name, **kwargs)

    def test_only_actions_that_can_filter_come_back(self):
        # A caller uses the returned keys to decide which actions are usable, so an action that
        # cannot narrow anything must be absent rather than present with a condition that matches
        # everything. A stepless action is the trap: `steps_to_expr` compiles it to a constant true.
        live = self._action("Completed checkout")
        stepless = self._action("Never finished", steps_json=[])
        deleted = self._action("Removed", deleted=True)

        conditions = action_filter_conditions(team=self.team, action_ids=[live.id, stepless.id, deleted.id])

        assert list(conditions) == [live.id]

    def test_an_action_outside_the_project_is_never_returned(self):
        # The ids reach this function from a search, so trusting them would let a caller compile a
        # filter against another project's action.
        other_team = Team.objects.create(organization=self.organization, name="other")
        theirs = Action.objects.create(team=other_team, name="Theirs", steps_json=[{"event": "checkout completed"}])

        assert action_filter_conditions(team=self.team, action_ids=[theirs.id]) == {}


class TestActionReads(APIBaseTest):
    def setUp(self):
        super().setUp()
        other_org = Organization.objects.create(name="other org")
        self.other_team = Team.objects.create(organization=other_org, name="other")

    def test_the_contract_carries_the_stored_action(self):
        model = Action.objects.create(
            team=self.team,
            name="Signed up",
            description="Finished the form",
            created_by=self.user,
            steps_json=[{"event": "$pageview", "url": "/signup", "url_matching": "exact"}, {"event": None}],
        )

        action = api.get_action(action_id=model.id, project_id=self.team.project_id)

        assert action.id == model.id
        assert action.team_id == self.team.id
        assert action.name == "Signed up"
        assert action.description == "Finished the form"
        assert action.created_by_id == self.user.id
        assert action.steps == (
            contracts.ActionStep(event="$pageview", url="/signup", url_matching="exact"),
            contracts.ActionStep(event=None),
        )
        assert action.get_step_events() == ["$pageview", None]
        assert action.created_at == model.created_at

    @parameterized.expand(
        [
            ("by project", {"include_deleted": True}, True),
            ("live only", {"include_deleted": False}, False),
        ]
    )
    def test_a_deleted_action_is_found_unless_live_only_is_asked(self, _name, kwargs, found):
        deleted = Action.objects.create(team=self.team, name="Gone", deleted=True)

        if found:
            assert api.get_action(action_id=deleted.id, project_id=self.team.project_id, **kwargs).deleted
        else:
            with self.assertRaises(contracts.ActionNotFound):
                api.get_action(action_id=deleted.id, project_id=self.team.project_id, **kwargs)

    def test_another_projects_action_is_not_found_in_any_scope(self):
        theirs = Action.objects.create(team=self.other_team, name="Theirs")

        with self.assertRaises(contracts.ActionNotFound):
            api.get_action(action_id=theirs.id, project_id=self.team.project_id)
        with self.assertRaises(contracts.ActionNotFound):
            api.get_action(action_id=theirs.id, team_id=self.team.id)
        assert api.get_actions(action_ids=[theirs.id], project_id=self.team.project_id) == []
        assert api.get_action_names(project_id=self.team.project_id, action_ids=[theirs.id]) == {}
        assert api.existing_action_ids(project_id=self.team.project_id, action_ids=[theirs.id]) == []

    def test_a_read_must_name_one_scope(self):
        with self.assertRaises(ValueError):
            api.get_action(action_id=1)
        with self.assertRaises(ValueError):
            api.get_action(action_id=1, project_id=self.team.project_id, team_id=self.team.id)

    def test_name_lookups_follow_the_scope_and_the_deleted_flag(self):
        live = Action.objects.create(team=self.team, name="Same")
        deleted = Action.objects.create(team=self.team, name="Same", deleted=True)
        Action.objects.create(team=self.other_team, name="Same")

        assert [action.id for action in api.find_actions_by_name(team_id=self.team.id, name="Same")] == [live.id]
        assert [
            action.id
            for action in api.find_actions_by_name(project_id=self.team.project_id, name="Same", include_deleted=True)
        ] == [live.id, deleted.id]
        assert api.get_action_names(project_id=self.team.project_id, action_ids=[live.id, deleted.id]) == {
            live.id: "Same",
            deleted.id: "Same",
        }

    def test_top_actions_put_pinned_first_then_the_most_recently_calculated(self):
        now = datetime(2026, 1, 1, tzinfo=UTC)
        older = Action.objects.create(team=self.team, name="older", last_calculated_at=now - timedelta(days=2))
        newer = Action.objects.create(team=self.team, name="newer", last_calculated_at=now - timedelta(days=1))
        pinned = Action.objects.create(
            team=self.team, name="pinned", pinned_at=now, last_calculated_at=now - timedelta(days=9)
        )
        Action.objects.create(team=self.team, name="deleted", deleted=True, last_calculated_at=now)

        top = api.list_top_actions(project_id=self.team.project_id, limit=2)

        assert [action.id for action in top] == [pinned.id, newer.id]
        assert older.id not in {action.id for action in top}

    def test_find_action_team_id_is_unscoped_and_can_skip_deleted(self):
        theirs = Action.objects.create(team=self.other_team, name="Theirs", deleted=True)

        assert api.find_action_team_id(action_id=theirs.id) == self.other_team.id
        assert api.find_action_team_id(action_id=theirs.id, include_deleted=False) is None


class TestActionAccessReads(APIBaseTest):
    def test_access_filtered_reads_return_only_live_actions_of_the_team(self):
        live = Action.objects.create(team=self.team, name="Checkout", description="x" * 300)
        deleted = Action.objects.create(team=self.team, name="Gone", deleted=True)
        access_control = UserAccessControl(self.user, team=self.team)

        assert api.accessible_action_ids(
            team_id=self.team.id, action_ids=[live.id, deleted.id], access_control=access_control
        ) == {live.id}
        catalog = api.list_action_catalog(team_id=self.team.id, access_control=access_control, limit=10)
        assert [(entry.id, entry.name, len(entry.short_description or "")) for entry in catalog] == [
            (live.id, "Checkout", 200)
        ]
        assert api.readable_action_ids(
            project_id=self.team.project_id, action_ids=[live.id, deleted.id], access_control=access_control
        ) == {live.id, deleted.id}

    def test_search_ranks_by_name_and_can_leave_deleted_out(self):
        match = Action.objects.create(team=self.team, name="purchase completed")
        deleted = Action.objects.create(team=self.team, name="purchase abandoned", deleted=True)
        Action.objects.create(team=self.team, name="signed up")
        access_control = UserAccessControl(self.user, team=self.team)

        results, count = api.search_actions(
            project_id=self.team.project_id, query="purchase", access_control=access_control, limit=10
        )
        live_results, live_count = api.search_actions(
            project_id=self.team.project_id,
            query="purchase",
            access_control=access_control,
            limit=10,
            include_deleted=False,
            with_access_levels=True,
        )

        assert count == 2
        assert {result["result_id"] for result in results} == {str(match.id), str(deleted.id)}
        assert live_count == 1
        assert live_results == [
            {
                "type": "action",
                "result_id": str(match.id),
                "extra_fields": {"name": "purchase completed", "description": ""},
                "rank": live_results[0]["rank"],
                "user_access_level": live_results[0]["user_access_level"],
            }
        ]


class TestActionWrites(APIBaseTest):
    def test_create_action_moves_a_child_environment_to_the_root_team_and_compiles(self):
        child = Team.objects.create(organization=self.organization, project=self.project, name="child")
        child.parent_team = self.team
        child.save()

        action = api.create_action(team=child, name="Viewed", steps_json=[{"event": "$pageview"}])

        assert action.team_id == self.team.id
        assert testing.get_action_bytecode(action).bytecode is not None

    def test_save_handlers_hear_every_save(self):
        handler = MagicMock()
        api.on_action_saved(handler, dispatch_uid="test_save_handlers_hear_every_save")
        try:
            action = testing.create_action(team=self.team, name="Viewed", steps_json=[{"event": "$pageview"}])
            testing.update_action(action, name="Renamed")
        finally:
            saved_handlers._handlers.pop("test_save_handlers_hear_every_save")

        assert [call.args[0] for call in handler.call_args_list] == [
            contracts.ActionSaved(action_id=action.id, team_id=self.team.id, created=True),
            contracts.ActionSaved(action_id=action.id, team_id=self.team.id, created=False),
        ]

    def test_update_action_recompiles_and_can_backdate(self):
        action = testing.create_action(team=self.team, name="Viewed", steps_json=[{"event": "$pageview"}])
        before = testing.get_action_bytecode(action).bytecode
        backdated = datetime(2020, 1, 1, tzinfo=UTC)

        updated = testing.update_action(action, steps_json=[{"event": "$autocapture"}], updated_at=backdated)

        assert updated.get_step_events() == ["$autocapture"]
        assert updated.updated_at == backdated
        assert testing.get_action_bytecode(action).bytecode != before


class TestActionSummariesAndEmbeddings(APIBaseTest):
    def _actions(self) -> list[Action]:
        return [Action.objects.create(team=self.team, name=f"action {index}") for index in range(3)]

    def test_actions_to_summarize_page_in_a_fixed_order(self):
        actions = self._actions()
        now = datetime.now(UTC)

        page = async_to_sync(api.alist_actions_to_summarize)(start_dt=now, offset=1, batch_size=1)

        assert async_to_sync(api.acount_actions_to_summarize)(start_dt=now) == 3
        assert [action.id for action in page] == [actions[1].id]
        assert async_to_sync(api.acount_actions_to_summarize)(start_dt=now - timedelta(days=1)) == 0
        with self.assertRaises(ValueError):
            async_to_sync(api.alist_actions_to_summarize)(start_dt=now, offset=1)

    def test_an_unreadable_action_is_left_out_of_the_page_without_failing_it(self):
        readable, unreadable, last = self._actions()
        Action.objects.filter(id=unreadable.id).update(steps_json=[{"event": "x", "legacy_key": 1}])

        page = async_to_sync(api.alist_actions_to_summarize)(start_dt=datetime.now(UTC), offset=0, batch_size=3)

        assert [action.id for action in page] == [readable.id, last.id]

    def test_deleted_actions_are_summarized_only_after_an_edit(self):
        never_summarized, edited, _ = self._actions()
        start_dt = datetime.now(UTC)
        Action.objects.filter(id=never_summarized.id).update(deleted=True)
        Action.objects.filter(id=edited.id).update(
            deleted=True,
            updated_at=start_dt - timedelta(hours=1),
            last_summarized_at=start_dt - timedelta(hours=2),
        )

        page = async_to_sync(api.alist_actions_to_summarize)(start_dt=start_dt + timedelta(hours=1))

        assert never_summarized.id not in {action.id for action in page}
        assert edited.id in {action.id for action in page}

    def test_an_organization_without_ai_consent_is_never_summarized(self):
        self._actions()
        self.organization.is_ai_data_processing_approved = False
        self.organization.save()

        assert async_to_sync(api.acount_actions_to_summarize)(start_dt=datetime.now(UTC)) == 0

    def test_summaries_then_embeddings_round_trip(self):
        first, second, _ = self._actions()
        summarized_at = datetime.now(UTC)

        async_to_sync(api.asave_action_summaries)(
            summaries={first.id: "summary one", second.id: "summary two"}, summarized_at=summarized_at
        )
        to_embed = async_to_sync(api.alist_actions_to_embed)(
            start_dt=summarized_at, embedding_version=None, offset=0, limit=10
        )
        async_to_sync(api.amark_actions_embedded)(
            action_ids=[action.id for action in to_embed], synced_at=summarized_at, embedding_version=2
        )

        assert [(action.id, action.summary) for action in to_embed] == [
            (first.id, "summary one"),
            (second.id, "summary two"),
        ]
        assert (
            async_to_sync(api.alist_actions_to_embed)(start_dt=summarized_at, embedding_version=2, offset=0, limit=10)
            == []
        )
        assert set(Action.objects.filter(embedding_version=2).values_list("id", flat=True)) == {first.id, second.id}
