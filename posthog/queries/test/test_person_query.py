from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_person, flush_persons_and_events

from posthog.clickhouse.client import sync_execute
from posthog.models import Filter
from posthog.models.cohort import Cohort
from posthog.queries.column_optimizer.column_optimizer import ColumnOptimizer
from posthog.queries.person_query import PersonQuery


class TestPersonQuery(ClickhouseTestMixin, APIBaseTest):
    @freeze_time("2021-01-01T00:00:00Z")
    def test_cohort_join_moves_into_prefiltering_subquery_with_person_property_filters(self):
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["p1"],
            properties={"in_cohort": "yes", "color": "blue"},
        )
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["p2"],
            properties={"in_cohort": "yes", "color": "blue"},
        )
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["p3"],
            properties={"in_cohort": "yes", "color": "red"},
        )
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["p4"],
            properties={"in_cohort": "no", "color": "blue"},
        )
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["p5"],
            properties={"in_cohort": "no", "color": "red"},
        )
        flush_persons_and_events()

        cohort = Cohort.objects.create(
            team=self.team,
            name="in_cohort_yes",
            groups=[{"properties": [{"key": "in_cohort", "value": "yes", "type": "person"}]}],
        )
        cohort.calculate_people_ch(pending_version=0)

        filter = Filter(
            data={
                "properties": [
                    {"key": "color", "value": "blue", "type": "person"},
                ],
            }
        )

        column_optimizer = ColumnOptimizer(filter, self.team.pk)
        person_query = PersonQuery(
            filter=filter,
            team_id=self.team.pk,
            column_optimizer=column_optimizer,
            cohort=cohort,
        )

        sql, params = person_query.get_query()

        # When person property filters are present (causing prefiltering), the cohort INNER JOIN
        # should be inside the prefiltering subquery, not at the top level
        assert "AND id IN" in sql, "Expected a prefiltering subquery"

        # The INNER JOIN for the cohort should appear inside the prefiltering subquery
        prefiltering_start = sql.index("AND id IN")
        prefiltering_end = sql.index(")", prefiltering_start + len("AND id IN ("))
        prefiltering_subquery = sql[prefiltering_start:prefiltering_end]
        assert "INNER JOIN" in prefiltering_subquery, (
            "Expected the cohort INNER JOIN to be inside the prefiltering subquery"
        )

        # The top-level query should NOT have the cohort INNER JOIN (it was moved into prefiltering)
        top_level_sql = sql[:prefiltering_start] + sql[sql.index(")", prefiltering_end) :]
        # Count INNER JOINs outside the prefiltering subquery — should be 0
        assert "INNER JOIN" not in top_level_sql, "Expected no top-level INNER JOIN when prefiltering is active"

        # Execute the query and verify the correct number of results
        results = sync_execute(sql, params)
        assert len(results) == 2, f"Expected 2 persons (in cohort + color=blue), got {len(results)}"
