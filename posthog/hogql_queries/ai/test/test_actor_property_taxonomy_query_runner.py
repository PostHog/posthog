from django.test import override_settings

from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql_queries.ai.actor_property_taxonomy_query_runner import ActorPropertyTaxonomyQueryRunner
from posthog.models.group.util import create_group
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.schema import ActorPropertyTaxonomyQuery
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_person,
    snapshot_clickhouse_queries,
)


@override_settings(IN_UNIT_TESTING=True)
class TestActorTaxonomyTaxonomyQueryRunner(ClickhouseTestMixin, APIBaseTest):
    @snapshot_clickhouse_queries
    def test_person_property_taxonomy_query_runner(self):
        _create_person(
            distinct_ids=["person1"],
            properties={"email": "person1@example.com", "name": "Person One", "age": 30},
            team=self.team,
        )
        _create_person(
            distinct_ids=["person2"],
            properties={"email": "person2@example.com", "age": 30},
            team=self.team,
        )
        _create_person(
            distinct_ids=["person3"],
            properties={"email": "person3@example.com"},
            team=self.team,
        )

        # regular person property
        results = ActorPropertyTaxonomyQueryRunner(
            team=self.team, query=ActorPropertyTaxonomyQuery(type="person", property="email")
        ).calculate()
        self.assertEqual(len(results.results.sample_values), 3)
        self.assertEqual(
            set(results.results.sample_values), {"person1@example.com", "person2@example.com", "person3@example.com"}
        )
        self.assertEqual(results.results.sample_count, 3)

        # does not exist
        results = ActorPropertyTaxonomyQueryRunner(
            team=self.team, query=ActorPropertyTaxonomyQuery(type="person", property="does not exist")
        ).calculate()
        self.assertEqual(len(results.results.sample_values), 0)
        self.assertEqual(results.results.sample_count, 0)

        # Ensure only distinct values are returned
        results = ActorPropertyTaxonomyQueryRunner(
            team=self.team, query=ActorPropertyTaxonomyQuery(type="person", property="age")
        ).calculate()
        self.assertEqual(len(results.results.sample_values), 1)
        self.assertEqual(results.results.sample_count, 1)
        # Ensure the value is a string
        self.assertEqual(results.results.sample_values[0], "30")

    @snapshot_clickhouse_queries
    def test_group_property_taxonomy_query_runner(self):
        GroupTypeMapping.objects.create(team=self.team, group_type="Company", group_type_index=0)
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="Hooli",
            properties={"industry": "tech", "employee_count": 30},
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="Pied Piper",
            properties={"industry": "energy", "employee_count": 30},
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="BYG",
            properties={"industry": "ecommerce"},
        )

        # regular group property
        results = ActorPropertyTaxonomyQueryRunner(
            team=self.team, query=ActorPropertyTaxonomyQuery(type="group", property="industry", group_type_index=0)
        ).calculate()
        self.assertEqual(len(results.results.sample_values), 3)
        self.assertEqual(set(results.results.sample_values), {"tech", "energy", "ecommerce"})
        self.assertEqual(results.results.sample_count, 3)

        # does not exist
        results = ActorPropertyTaxonomyQueryRunner(
            team=self.team,
            query=ActorPropertyTaxonomyQuery(type="group", property="does not exist", group_type_index=0),
        ).calculate()
        self.assertEqual(len(results.results.sample_values), 0)
        self.assertEqual(results.results.sample_count, 0)

        # Ensure only distinct values are returned
        results = ActorPropertyTaxonomyQueryRunner(
            team=self.team,
            query=ActorPropertyTaxonomyQuery(type="group", property="employee_count", group_type_index=0),
        ).calculate()
        self.assertEqual(len(results.results.sample_values), 1)
        self.assertEqual(results.results.sample_count, 1)
        # Ensure the value is a string
        self.assertEqual(results.results.sample_values[0], "30")

    def test_group_property_taxonomy_query_runner_with_none_group_type_index(self):
        with self.assertRaises(ExposedHogQLError) as context:
            ActorPropertyTaxonomyQueryRunner(
                team=self.team,
                query=ActorPropertyTaxonomyQuery(type="group", property="industry"),
            ).calculate()
        self.assertEqual(str(context.exception), "group_type_index must be an integer.")
