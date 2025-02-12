from django.test import override_settings

from posthog.hogql_queries.ai.actors_property_taxonomy_query_runner import ActorsPropertyTaxonomyQueryRunner
from posthog.models.group.util import create_group
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.schema import ActorsPropertyTaxonomyQuery
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_person,
    snapshot_clickhouse_queries,
)


@override_settings(IN_UNIT_TESTING=True)
class TestActorsPropertyTaxonomyQueryRunner(ClickhouseTestMixin, APIBaseTest):
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
        results = ActorsPropertyTaxonomyQueryRunner(
            team=self.team, query=ActorsPropertyTaxonomyQuery(property="email")
        ).calculate()
        self.assertEqual(len(results.results.sample_values), 3)
        self.assertEqual(
            set(results.results.sample_values), {"person1@example.com", "person2@example.com", "person3@example.com"}
        )
        self.assertEqual(results.results.sample_count, 3)

        # does not exist
        results = ActorsPropertyTaxonomyQueryRunner(
            team=self.team, query=ActorsPropertyTaxonomyQuery(property="does not exist")
        ).calculate()
        self.assertEqual(len(results.results.sample_values), 0)
        self.assertEqual(results.results.sample_count, 0)

        # Ensure only distinct values are returned
        results = ActorsPropertyTaxonomyQueryRunner(
            team=self.team, query=ActorsPropertyTaxonomyQuery(property="age")
        ).calculate()
        self.assertEqual(len(results.results.sample_values), 1)
        self.assertEqual(results.results.sample_count, 1)
        # Ensure the value is a string
        self.assertEqual(results.results.sample_values[0], "30")

    @snapshot_clickhouse_queries
    def test_group_property_taxonomy_query_runner(self):
        GroupTypeMapping.objects.create(
            team=self.team, project_id=self.team.project_id, group_type="Company", group_type_index=0
        )
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
        results = ActorsPropertyTaxonomyQueryRunner(
            team=self.team, query=ActorsPropertyTaxonomyQuery(property="industry", group_type_index=0)
        ).calculate()
        self.assertEqual(len(results.results.sample_values), 3)
        self.assertEqual(set(results.results.sample_values), {"tech", "energy", "ecommerce"})
        self.assertEqual(results.results.sample_count, 3)

        # does not exist
        results = ActorsPropertyTaxonomyQueryRunner(
            team=self.team,
            query=ActorsPropertyTaxonomyQuery(property="does not exist", group_type_index=0),
        ).calculate()
        self.assertEqual(len(results.results.sample_values), 0)
        self.assertEqual(results.results.sample_count, 0)

        # Ensure only distinct values are returned
        results = ActorsPropertyTaxonomyQueryRunner(
            team=self.team,
            query=ActorsPropertyTaxonomyQuery(property="employee_count", group_type_index=0),
        ).calculate()
        self.assertEqual(len(results.results.sample_values), 1)
        self.assertEqual(results.results.sample_count, 1)
        # Ensure the value is a string
        self.assertEqual(results.results.sample_values[0], "30")

    @snapshot_clickhouse_queries
    def test_max_value_count(self):
        _create_person(
            distinct_ids=["person1"],
            properties={"age": 29},
            team=self.team,
        )
        _create_person(
            distinct_ids=["person2"],
            properties={"age": 30},
            team=self.team,
        )
        _create_person(
            distinct_ids=["person3"],
            properties={"age": 31},
            team=self.team,
        )

        # regular person property
        results = ActorsPropertyTaxonomyQueryRunner(
            team=self.team, query=ActorsPropertyTaxonomyQuery(property="age", maxPropertyValues=1)
        ).calculate()
        self.assertEqual(len(results.results.sample_values), 1)
        self.assertEqual(results.results.sample_count, 3)
