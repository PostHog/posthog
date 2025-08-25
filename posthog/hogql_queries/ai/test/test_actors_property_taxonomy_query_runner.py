from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_person, snapshot_clickhouse_queries

from django.test import override_settings

from posthog.schema import ActorsPropertyTaxonomyQuery, ActorsPropertyTaxonomyResponse

from posthog.hogql_queries.ai.actors_property_taxonomy_query_runner import ActorsPropertyTaxonomyQueryRunner
from posthog.models import PropertyDefinition
from posthog.models.group.util import create_group
from posthog.models.property_definition import PropertyType
from posthog.test.test_utils import create_group_type_mapping_without_created_at


@override_settings(IN_UNIT_TESTING=True)
class TestActorsPropertyTaxonomyQueryRunner(ClickhouseTestMixin, APIBaseTest):
    def _run(self, query: ActorsPropertyTaxonomyQuery) -> list[ActorsPropertyTaxonomyResponse]:
        response = ActorsPropertyTaxonomyQueryRunner(team=self.team, query=query).calculate()
        if not isinstance(response.results, list):
            raise ValueError("Response is not an ActorsPropertyTaxonomyQueryResponse")
        return response.results

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
        results = self._run(ActorsPropertyTaxonomyQuery(properties=["email"]))

        self.assertEqual(len(results[0].sample_values), 3)
        self.assertEqual(
            set(results[0].sample_values), {"person1@example.com", "person2@example.com", "person3@example.com"}
        )
        self.assertEqual(results[0].sample_count, 3)

        # does not exist
        results = self._run(ActorsPropertyTaxonomyQuery(properties=["does not exist"]))
        self.assertEqual(len(results[0].sample_values), 0)
        self.assertEqual(results[0].sample_count, 0)

        # Ensure only distinct values are returned
        results = self._run(ActorsPropertyTaxonomyQuery(properties=["age"]))
        self.assertEqual(len(results[0].sample_values), 1)
        self.assertEqual(results[0].sample_count, 1)
        # Ensure the value is a string
        self.assertEqual(results[0].sample_values[0], "30")

    @snapshot_clickhouse_queries
    def test_group_property_taxonomy_query_runner(self):
        create_group_type_mapping_without_created_at(
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
        results = self._run(ActorsPropertyTaxonomyQuery(properties=["industry"], groupTypeIndex=0))
        self.assertEqual(len(results[0].sample_values), 3)
        self.assertEqual(set(results[0].sample_values), {"tech", "energy", "ecommerce"})
        self.assertEqual(results[0].sample_count, 3)

        # does not exist
        results = self._run(ActorsPropertyTaxonomyQuery(properties=["does not exist"], groupTypeIndex=0))
        self.assertEqual(len(results[0].sample_values), 0)
        self.assertEqual(results[0].sample_count, 0)

        # Ensure only distinct values are returned
        results = self._run(ActorsPropertyTaxonomyQuery(properties=["employee_count"], groupTypeIndex=0))
        self.assertEqual(len(results[0].sample_values), 1)
        self.assertEqual(results[0].sample_count, 1)
        # Ensure the value is a string
        self.assertEqual(results[0].sample_values[0], "30")

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
        results = self._run(ActorsPropertyTaxonomyQuery(properties=["age"], maxPropertyValues=1))
        self.assertEqual(len(results[0].sample_values), 1)
        self.assertEqual(results[0].sample_count, 3)

    def test_multiple_properties(self):
        PropertyDefinition.objects.create(team=self.team, name="age", property_type=PropertyType.Numeric)

        _create_person(
            distinct_ids=["person1"],
            properties={"age": 29},
            team=self.team,
        )
        _create_person(
            distinct_ids=["person2"],
            properties={"age": 30, "name": "Person Two"},
            team=self.team,
        )
        _create_person(
            distinct_ids=["person3"],
            properties={"age": 31},
            team=self.team,
        )

        # regular person property
        results = self._run(ActorsPropertyTaxonomyQuery(properties=["age", "name"], maxPropertyValues=10))
        self.assertIsInstance(results, list)
        self.assertEqual(len(results), 2)
        self.assertEqual(len(results[0].sample_values), 3)
        self.assertEqual(results[0].sample_count, 3)
        self.assertEqual(len(results[1].sample_values), 1)
        self.assertEqual(results[1].sample_count, 1)
        self.assertEqual(set(results[1].sample_values), {"Person Two"})

        results = self._run(ActorsPropertyTaxonomyQuery(properties=["name"], maxPropertyValues=10))
        self.assertIsInstance(results, list)
        self.assertEqual(len(results), 1)
        self.assertEqual(len(results[0].sample_values), 1)
        self.assertEqual(results[0].sample_count, 1)
        self.assertEqual(set(results[0].sample_values), {"Person Two"})
