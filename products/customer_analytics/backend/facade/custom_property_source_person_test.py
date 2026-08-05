from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.customer_analytics.backend.facade import api
from products.customer_analytics.backend.models import CustomPropertySource, TargetType
from products.customer_analytics.backend.models.team_scoped_test_base import TeamScopedTestMixin
from products.customer_analytics.backend.test.factories import create_custom_property_definition
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource


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
                "person_without_schema",
                {"external_data_schema_id": None},
                "needs an external_data_schema",
            ),
            (
                "person_with_saved_query_binding",
                {"saved_query_id": uuid4()},
                "not saved_query",
            ),
            (
                "person_with_source_column_binding",
                {"source_column": "plan"},
                "not saved_query",
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

        allowed = api.get_custom_property_source(self.team.id, source.id, user_access_control=self._uac(allowed=True))
        assert allowed is not None
        assert allowed.sync_frequency_interval_seconds == timedelta(hours=6).total_seconds()
        assert allowed.last_sync_error == "boom: internal warehouse detail" and allowed.consecutive_failures == 3
        assert allowed.column_descriptions == {"plan": "internal warehouse column note"}

    def test_list_sync_runs_requires_warehouse_source_viewer(self):
        source = self._create(user_access_control=self._uac(allowed=True))
        with self.assertRaises(api.ResourceForbiddenError):
            api.list_custom_property_sync_runs(
                self.team.id, source.id, offset=0, limit=10, user_access_control=self._uac(allowed=False)
            )

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
