from uuid import uuid4

from posthog.test.base import APIBaseTest

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
