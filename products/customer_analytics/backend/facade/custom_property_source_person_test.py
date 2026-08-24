from datetime import timedelta
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from parameterized import parameterized

from products.customer_analytics.backend.facade import api
from products.customer_analytics.backend.models import CustomPropertySource, CustomPropertySyncRun, TargetType
from products.customer_analytics.backend.models.team_scoped_test_base import TeamScopedTestMixin
from products.customer_analytics.backend.test.factories import create_custom_property_definition, create_saved_query
from products.warehouse_sources.backend.models.credential import DataWarehouseCredential
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import DataWarehouseTable


class TestPersonCustomPropertySource(TeamScopedTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        self.person_def = create_custom_property_definition(
            team_id=self.team.id, name="Plan tier", target_type=TargetType.PERSON.value
        )
        self.account_def = create_custom_property_definition(
            team_id=self.team.id, name="MRR", target_type=TargetType.ACCOUNT.value
        )
        source = ExternalDataSource.objects.create(
            team=self.team, source_id="s", connection_id="c", status="Running", source_type="Stripe"
        )
        self.schema = ExternalDataSchema.objects.create(team=self.team, source=source, name="users")
        self.saved_query = create_saved_query(team_id=self.team.id)

    def _create(self, **overrides):
        kwargs: dict = {
            "team_id": self.team.id,
            "definition_id": self.person_def.id,
            "key_column": "distinct_id",
            "is_enabled": True,
            "user": self.user,
            "external_data_schema_id": self.schema.id,
            "column_property_map": {"plan": "plan_tier"},
        }
        kwargs.update(overrides)
        return api.create_custom_property_source(**kwargs)

    def test_create_person_source_round_trips(self):
        view = self._create(column_property_map={"plan": "plan_tier", "seats": "seat_count"})

        assert view.external_data_schema == self.schema.id
        assert view.column_property_map == {"plan": "plan_tier", "seats": "seat_count"}
        assert view.key_column == "distinct_id"
        assert view.saved_query is None
        assert not view.source_column

        row = CustomPropertySource.objects.unscoped().get(id=view.id)
        assert row.external_data_schema_id == self.schema.id
        assert row.column_property_map == {"plan": "plan_tier", "seats": "seat_count"}
        assert row.saved_query_id is None

    def test_create_person_source_stores_and_cleans_column_descriptions(self):
        view = self._create(
            column_property_map={"plan": "plan_tier", "seats": "seat_count"},
            # 'plan' kept and trimmed; 'seats' blank -> dropped; 'unmapped' -> dropped (no such column).
            column_descriptions={"plan": "  The plan tier  ", "seats": "   ", "unmapped": "ignored"},
        )

        assert view.column_descriptions == {"plan": "The plan tier"}
        row = CustomPropertySource.objects.unscoped().get(id=view.id)
        assert row.column_descriptions == {"plan": "The plan tier"}

    def test_create_person_source_defaults_descriptions_to_empty(self):
        view = self._create()
        assert view.column_descriptions == {}

    def test_person_source_rejects_non_object_column_descriptions(self):
        with self.assertRaisesMessage(api.CustomPropertySourceValidationError, "must be an object"):
            self._create(column_descriptions=["not", "an", "object"])

    @parameterized.expand(
        [
            (
                "person_without_a_binding",
                {"external_data_schema_id": None},
                "exactly one of external_data_schema and saved_query",
            ),
            (
                "person_with_both_bindings",
                {"saved_query_id": uuid4()},
                "exactly one of external_data_schema and saved_query",
            ),
            (
                "person_with_source_column",
                {"source_column": "plan"},
                "not source_column",
            ),
            (
                "person_empty_map",
                {"column_property_map": {}},
                "non-empty object",
            ),
            (
                "person_blank_property_name",
                {"column_property_map": {"plan": ""}},
                "non-empty property names",
            ),
            (
                "person_blank_column_name",
                {"column_property_map": {"": "plan_tier"}},
                "non-empty column names",
            ),
        ]
    )
    def test_person_source_validation(self, _name, overrides, expected_message):
        with self.assertRaises(api.CustomPropertySourceValidationError) as ctx:
            self._create(**overrides)
        assert expected_message in str(ctx.exception)

    def test_person_source_rejects_schema_from_another_team(self):
        other_team_source = ExternalDataSource.objects.create(
            team=self.organization.teams.create(name="other"),
            source_id="s2",
            connection_id="c2",
            status="Running",
            source_type="Stripe",
        )
        foreign_schema = ExternalDataSchema.objects.create(
            team=other_team_source.team, source=other_team_source, name="users"
        )
        with self.assertRaises(api.CustomPropertySourceValidationError) as ctx:
            self._create(external_data_schema_id=foreign_schema.id)
        assert "not found for this team" in str(ctx.exception)

    @parameterized.expand(
        [
            (
                "account_with_schema_binding",
                {"saved_query_id": uuid4(), "source_column": "c", "external_data_schema_id": uuid4()},
                "not external_data_schema",
            ),
            (
                "account_with_column_map_binding",
                {"saved_query_id": uuid4(), "source_column": "c", "column_property_map": {"a": "b"}},
                "not external_data_schema",
            ),
            (
                "account_without_saved_query",
                {
                    "saved_query_id": None,
                    "source_column": None,
                    "external_data_schema_id": None,
                    "column_property_map": None,
                },
                "needs a saved_query",
            ),
        ]
    )
    def test_account_source_validation(self, _name, overrides, expected_message):
        with self.assertRaises(api.CustomPropertySourceValidationError) as ctx:
            self._create(definition_id=self.account_def.id, **overrides)
        assert expected_message in str(ctx.exception)

    @staticmethod
    def _uac(allowed: bool) -> MagicMock:
        uac = MagicMock()
        uac.check_access_level_for_object.return_value = allowed
        return uac

    def test_create_person_source_requires_warehouse_source_editor(self):
        # Mapping a warehouse table into person properties drives its billable source, so a caller
        # without external_data_source editor access is refused even with account-scope editor.
        with self.assertRaises(api.ResourceForbiddenError):
            self._create(user_access_control=self._uac(allowed=False))
        # The allow path still creates the source.
        view = self._create(user_access_control=self._uac(allowed=True))
        assert view.external_data_schema == self.schema.id

    @patch("products.customer_analytics.backend.facade.api.person_properties_flag_enabled", return_value=True)
    def test_trigger_sync_denied_without_warehouse_source_editor(self, _flag):
        source = self._create()
        with self.assertRaises(api.ResourceForbiddenError):
            api.trigger_person_property_sync(
                team_id=self.team.id, source_id=source.id, user_access_control=self._uac(allowed=False)
            )

    @patch("products.customer_analytics.backend.facade.api.person_properties_flag_enabled", return_value=True)
    def test_trigger_backfill_denied_without_warehouse_source_editor(self, _flag):
        source = self._create()
        with self.assertRaises(api.ResourceForbiddenError):
            api.trigger_person_property_backfill(
                team_id=self.team.id, source_id=source.id, user_access_control=self._uac(allowed=False)
            )

    def test_update_columns_requires_warehouse_source_editor(self):
        # Changing the mapped columns on an enabled person source auto-triggers a warehouse backfill, so
        # it needs external_data_source editor access, not account-scope editor alone — the gate must
        # cover column changes, not just re-enabling.
        source = self._create(user_access_control=self._uac(allowed=True))
        with self.assertRaises(api.ResourceForbiddenError):
            api.update_custom_property_source(
                team_id=self.team.id,
                source_id=source.id,
                fields={"key_column": "user_id"},
                user_access_control=self._uac(allowed=False),
            )

    def test_delete_person_source_requires_warehouse_source_editor(self):
        # Deleting a person source permanently stops its billable warehouse-driven updates, so it needs
        # external_data_source editor access, not account-scope editor alone.
        source = self._create(user_access_control=self._uac(allowed=True))
        with self.assertRaises(api.ResourceForbiddenError):
            api.delete_custom_property_source(
                team_id=self.team.id, source_id=source.id, user_access_control=self._uac(allowed=False)
            )
        assert CustomPropertySource.objects.filter(id=source.id).exists()
        assert api.delete_custom_property_source(
            team_id=self.team.id, source_id=source.id, user_access_control=self._uac(allowed=True)
        )
        assert not CustomPropertySource.objects.filter(id=source.id).exists()

    def test_disabling_source_does_not_require_warehouse_source_editor(self):
        # Disabling never triggers a backfill, so it must not demand warehouse editor access.
        source = self._create(user_access_control=self._uac(allowed=True))
        view = api.update_custom_property_source(
            team_id=self.team.id,
            source_id=source.id,
            fields={"is_enabled": False},
            user_access_control=self._uac(allowed=False),
        )
        assert view is not None and view.is_enabled is False

    def test_source_view_gates_warehouse_metadata_on_viewer_access(self):
        from datetime import timedelta  # noqa: PLC0415

        self.schema.sync_frequency_interval = timedelta(hours=6)
        self.schema.save(update_fields=["sync_frequency_interval"])
        source = self._create(
            user_access_control=self._uac(allowed=True),
            # Column descriptions come from the warehouse source's information_schema, so they're gated too.
            column_descriptions={"plan": "internal warehouse column note"},
        )
        # Warehouse-derived sync status, including the raw error text from the backfill/sync activity.
        CustomPropertySource.objects.filter(id=source.id).update(
            last_sync_error="boom: internal warehouse detail", consecutive_failures=3
        )

        denied = api.get_custom_property_source(self.team.id, source.id, user_access_control=self._uac(allowed=False))
        assert denied is not None
        assert denied.sync_frequency_interval_seconds is None and denied.next_sync_at is None
        # Status fields must be redacted too, not just the schedule — the raw error can leak warehouse detail.
        assert denied.last_sync_error is None and denied.consecutive_failures == 0
        # Column descriptions leak warehouse metadata to a caller without warehouse-source access.
        assert denied.column_descriptions == {}

        # The binding a link would be built from names a warehouse source the caller can't see.
        assert denied.external_data_source is None and denied.table_name is None

        allowed = api.get_custom_property_source(self.team.id, source.id, user_access_control=self._uac(allowed=True))
        assert allowed is not None
        assert allowed.sync_frequency_interval_seconds == timedelta(hours=6).total_seconds()
        assert allowed.last_sync_error == "boom: internal warehouse detail" and allowed.consecutive_failures == 3
        assert allowed.column_descriptions == {"plan": "internal warehouse column note"}
        assert allowed.external_data_source == self.schema.source_id
        # No table row yet, so the schema name is the best label available.
        assert allowed.table_name == "users"

    def test_source_view_names_the_bound_table_as_hogql_queries_it(self):
        credential = DataWarehouseCredential.objects.create(access_key="k", access_secret="s", team=self.team)
        self.schema.table = DataWarehouseTable.objects.create(
            team=self.team,
            name="stripe_users",
            format="Parquet",
            credential=credential,
            url_pattern="https://bucket.s3/data/*",
        )
        self.schema.save(update_fields=["table"])
        source = self._create(user_access_control=self._uac(allowed=True))

        view = api.get_custom_property_source(self.team.id, source.id, user_access_control=self._uac(allowed=True))

        assert view is not None
        assert view.table_name == "stripe.users"

    def test_list_sync_runs_requires_warehouse_source_viewer(self):
        source = self._create(user_access_control=self._uac(allowed=True))
        with self.assertRaises(api.ResourceForbiddenError):
            api.list_custom_property_sync_runs(
                self.team.id, source.id, offset=0, limit=10, user_access_control=self._uac(allowed=False)
            )

    @patch("products.warehouse_sources.backend.facade.temporal.trigger_schema_sync")
    @patch("products.customer_analytics.backend.facade.api.person_properties_flag_enabled", return_value=True)
    def test_trigger_sync_opens_a_running_run(self, _flag, _trigger_schema_sync):
        # The sync itself only records a run once it finishes, so without this the history stays blank
        # and the trigger buttons stay clickable for the whole import.
        source = self._create(user_access_control=self._uac(allowed=True))
        assert (
            api.trigger_person_property_sync(
                team_id=self.team.id, source_id=source.id, user_access_control=self._uac(allowed=True)
            )
            is True
        )

        run = CustomPropertySyncRun.objects.unscoped().get(source_id=source.id)
        assert run.status == "running" and run.trigger == "sync"
        assert run.started_at is not None and run.finished_at is None

    @patch(
        "products.warehouse_sources.backend.facade.temporal.trigger_schema_sync",
        side_effect=RuntimeError("temporal unreachable"),
    )
    @patch("products.customer_analytics.backend.facade.api.person_properties_flag_enabled", return_value=True)
    def test_trigger_sync_fails_its_run_when_the_sync_never_starts(self, _flag, _trigger_schema_sync):
        # Nothing downstream will reconcile a run whose sync never started, so it would sit 'running'
        # and keep the source's buttons disabled.
        source = self._create(user_access_control=self._uac(allowed=True))
        with self.assertRaises(RuntimeError):
            api.trigger_person_property_sync(
                team_id=self.team.id, source_id=source.id, user_access_control=self._uac(allowed=True)
            )

        run = CustomPropertySyncRun.objects.unscoped().get(source_id=source.id)
        assert run.status == "failed" and run.error == "Failed to start sync"

    @patch("products.customer_analytics.backend.facade.api.person_properties_flag_enabled", return_value=True)
    def test_backfill_fails_its_run_when_the_warehouse_object_is_gone(self, _flag):
        # Deleting the source's warehouse object soft-deletes the schema but leaves the source's binding,
        # so the backfill can't resolve a table. Without failing the placeholder it just created, the run
        # would sit 'running' until the stale-run sweep, and the trigger would report a coalesced run for a
        # table that no longer exists (returning False → 'already_running') instead of an invalid source.
        source = self._create(user_access_control=self._uac(allowed=True))
        ExternalDataSchema.objects.filter(id=self.schema.id).update(deleted=True)

        result = api.trigger_person_property_backfill(
            team_id=self.team.id, source_id=source.id, user_access_control=self._uac(allowed=True)
        )

        assert result is None
        run = CustomPropertySyncRun.objects.unscoped().get(source_id=source.id)
        assert run.status == "failed" and run.finished_at is not None

    @parameterized.expand(
        [
            ("stale", api.STALE_RUNNING_RUN_AFTER + timedelta(minutes=1), "failed"),
            ("in_flight", timedelta(minutes=5), "running"),
        ]
    )
    def test_abandoned_running_runs_expire_when_read(self, _name, age, expected_status):
        # A run whose activity died never reaches a terminal state on its own; left alone it reports the
        # source as perpetually syncing and blocks every retry.
        source = self._create(user_access_control=self._uac(allowed=True))
        run = CustomPropertySyncRun.objects.create(
            team_id=self.team.id,
            source_id=source.id,
            schema_id=self.schema.id,
            trigger="sync",
            status="running",
            started_at=timezone.now() - age,
        )

        views, _ = api.list_custom_property_sync_runs(
            self.team.id, source.id, offset=0, limit=10, user_access_control=self._uac(allowed=True)
        )

        assert views[0].status == expected_status
        run.refresh_from_db()
        assert run.status == expected_status

    def test_listing_sources_only_expires_runs_the_caller_can_view(self):
        # The source-list page expires abandoned running runs as it enriches. A caller denied
        # warehouse-source viewer access can't see the source's status, so it must not flip that
        # source's run either — otherwise the list endpoint mutates rows hidden from the caller.
        source = self._create(user_access_control=self._uac(allowed=True))
        run = CustomPropertySyncRun.objects.create(
            team_id=self.team.id,
            source_id=source.id,
            schema_id=self.schema.id,
            trigger="sync",
            status="running",
            started_at=timezone.now() - (api.STALE_RUNNING_RUN_AFTER + timedelta(minutes=1)),
        )

        api.list_custom_property_sources(self.team.id, offset=0, limit=10, user_access_control=self._uac(allowed=False))
        run.refresh_from_db()
        assert run.status == "running"

        api.list_custom_property_sources(self.team.id, offset=0, limit=10, user_access_control=self._uac(allowed=True))
        run.refresh_from_db()
        assert run.status == "failed"

    @patch("products.customer_analytics.backend.facade.api.person_properties_flag_enabled", return_value=True)
    def test_triggers_reject_disabled_source(self, _flag):
        # A disabled source can't be re-triggered: sync returns False (→ 400) and backfill None (→ 400).
        source = self._create(is_enabled=False)
        assert (
            api.trigger_person_property_sync(
                team_id=self.team.id, source_id=source.id, user_access_control=self._uac(allowed=True)
            )
            is False
        )
        assert (
            api.trigger_person_property_backfill(
                team_id=self.team.id, source_id=source.id, user_access_control=self._uac(allowed=True)
            )
            is None
        )

    # --- materialized-view bindings ------------------------------------------------------------

    def _create_view_source(self, **overrides):
        kwargs: dict = {"external_data_schema_id": None, "saved_query_id": self.saved_query.id}
        kwargs.update(overrides)
        return self._create(**kwargs)

    def test_create_view_backed_person_source_round_trips(self):
        view = self._create_view_source(user_access_control=self._uac(allowed=True))

        assert view.saved_query == self.saved_query.id
        assert view.external_data_schema is None
        assert view.column_property_map == {"plan": "plan_tier"}
        # The UI names and links a view-backed source off these, so both have to resolve.
        assert view.table_name == "enriched_users"
        assert view.saved_query_name == "enriched_users"
        assert view.external_data_source is None

        row = CustomPropertySource.objects.unscoped().get(id=view.id)
        assert row.saved_query_id == self.saved_query.id and row.external_data_schema_id is None

    def test_view_backed_person_source_rejects_an_unmaterialized_view(self):
        # A view with no materialization has no Delta table, so the source could never sync — an
        # accepted mapping would sit silently empty forever.
        unmaterialized = create_saved_query(team_id=self.team.id, name="draft_users", is_materialized=False)
        with self.assertRaisesMessage(api.CustomPropertySourceValidationError, "not found for this team"):
            self._create_view_source(saved_query_id=unmaterialized.id)

    def test_view_backed_person_source_rejects_a_view_from_another_team(self):
        foreign = create_saved_query(team_id=self.organization.teams.create(name="other").id, name="their_users")
        with self.assertRaisesMessage(api.CustomPropertySourceValidationError, "not found for this team"):
            self._create_view_source(saved_query_id=foreign.id)

    def test_create_view_backed_person_source_requires_view_editor(self):
        # Mapping a view into person properties drives real materializations, so it needs editor access
        # on the view, not account-scope editor alone — the same bar a table binding clears.
        with self.assertRaises(api.ResourceForbiddenError):
            self._create_view_source(user_access_control=self._uac(allowed=False))

    @patch("products.customer_analytics.backend.facade.api.person_properties_flag_enabled", return_value=True)
    def test_sync_now_materializes_the_view_and_opens_a_running_run(self, _flag):
        source = self._create_view_source(user_access_control=self._uac(allowed=True))
        with patch(
            "products.warehouse_sources.backend.facade.temporal.trigger_saved_query_materialization"
        ) as materialize:
            assert (
                api.trigger_person_property_sync(
                    team_id=self.team.id, source_id=source.id, user_access_control=self._uac(allowed=True)
                )
                is True
            )

        materialize.assert_called_once_with(team_id=self.team.id, saved_query_id=str(self.saved_query.id))
        run = CustomPropertySyncRun.objects.unscoped().get(source_id=source.id)
        # The run is attributed to the view, not to a schema it never read.
        assert run.saved_query_id == self.saved_query.id and run.schema_id is None
        assert run.status == "running" and run.trigger == "sync"

    @patch("products.customer_analytics.backend.facade.api.person_properties_flag_enabled", return_value=True)
    def test_sync_now_on_a_view_outside_v2_reports_it_and_fails_the_run(self, _flag):
        # Only the v2 materialization stages person-property rows. Starting a v1 run would look like a
        # successful "Sync now" while the properties never update, so it has to surface as an error.
        from products.warehouse_sources.backend.facade.temporal import SavedQueryNotOnV2ScheduleError

        source = self._create_view_source(user_access_control=self._uac(allowed=True))
        with patch(
            "products.warehouse_sources.backend.facade.temporal.trigger_saved_query_materialization",
            side_effect=SavedQueryNotOnV2ScheduleError("older data modeling schedule"),
        ):
            with self.assertRaises(api.ViewNotSyncableError):
                api.trigger_person_property_sync(
                    team_id=self.team.id, source_id=source.id, user_access_control=self._uac(allowed=True)
                )

        run = CustomPropertySyncRun.objects.unscoped().get(source_id=source.id)
        assert run.status == "failed" and "older data modeling schedule" in (run.error or "")

    @patch("products.customer_analytics.backend.facade.api.person_properties_flag_enabled", return_value=True)
    def test_backfill_targets_the_view_binding(self, _flag):
        source = self._create_view_source(user_access_control=self._uac(allowed=True))
        with patch(
            "products.warehouse_sources.backend.facade.temporal.start_person_property_backfill", return_value=True
        ) as start:
            assert (
                api.trigger_person_property_backfill(
                    team_id=self.team.id, source_id=source.id, user_access_control=self._uac(allowed=True)
                )
                is True
            )

        binding = start.call_args.kwargs["binding"]
        assert (binding.kind, binding.id) == ("saved_query", str(self.saved_query.id))
