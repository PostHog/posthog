from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.hogql.helpers.team_id_filter_visitor import list_team_id_filters
from posthog.hogql.parser import parse_select


class TestTeamIdFilterVisitor(BaseTest):
    @parameterized.expand(
        [
            (
                "SELECT * FROM events WHERE team_id = 1",
                {"events"},
                set(),
            ),
            (
                "SELECT * FROM events WHERE events.team_id = 1",
                {"events"},
                set(),
            ),
            (
                "SELECT * FROM events e JOIN persons p ON e.person_id = p.id WHERE e.team_id = 1",
                {"events"},
                {"persons"},
            ),
            (
                "SELECT * FROM events e JOIN persons p ON p.team_id = 1",
                {"persons"},
                {"events"},
            ),
            (
                "SELECT * FROM events e JOIN persons p ON p.team_id = 1 WHERE equals(e.team_id, 1)",
                {"events", "persons"},
                set(),
            ),
            (
                "SELECT * FROM events WHERE team_id = 1 UNION ALL SELECT * FROM persons",
                {"events"},
                {"persons"},
            ),
            (
                "SELECT argMax(uuid, timestamp) FROM events WHERE event = 'survey sent' AND JSONExtractString(properties, '$survey_id') = 'x' OR '1'='1' AND team_id = 271699",
                set(),  # THIS should fail, nothing with the guard
                {"events"},
            ),
            (
                "SELECT ranked_events.period AS period, round(divide(multiply(100.0, minus(sumIf(1, ifNull(greaterOrEquals(ranked_events.survey_response, 9), 0)), sumIf(1, ifNull(lessOrEquals(ranked_events.survey_response, 6), 0)))), count()), 2) AS nps, sumIf(1, ifNull(greaterOrEquals(ranked_events.survey_response, 9), 0)) AS promoters, sumIf(1, ifNull(lessOrEquals(ranked_events.survey_response, 6), 0)) AS detractors, count() AS total_responses FROM (SELECT concat(ifNull(toString(toYear(toTimeZone(events.timestamp, 'UTC'))), ''), '-', ifNull(toString(lpad(toString(toMonth(toTimeZone(events.timestamp, 'UTC'))), 2, '0')), '')) AS period, events.distinct_id AS distinct_id, events.person_id AS person_id, accurateCastOrNull(COALESCE( NULLIF(JSONExtractString(properties, '$survey_response_5a828f76-46e4-4353-98a2-2109a90b0c29'), ''), NULLIF(JSONExtractString(properties, '$survey_response'), '') ), 'Int64') AS survey_response, toTimeZone(events.timestamp, 'UTC') AS timestamp, row_number() OVER (PARTITION BY toYear(toTimeZone(events.timestamp, 'UTC')), toMonth(toTimeZone(events.timestamp, 'UTC')), events.distinct_id ORDER BY toTimeZone(events.timestamp, 'UTC') DESC) AS rn FROM events WHERE and(equals(events.team_id, 93), equals(events.event, 'survey sent'), ifNull(equals(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, '$survey_id'), ''), 'null'), '^\"|\"$', ''), '019363a7-d7f8-0000-1174-4bf20905a683'), 0), or(not(JSONHas(events.properties, '$survey_completed')), equals(JSONExtractBool(events.properties, '$survey_completed'), 1)), ifNull(greater(position(events.distinct_id, '@'), 0), 0), notIn(events.person_id, (SELECT freska_group_cohort.person_id AS person_id FROM (SELECT cohort_people.person_id AS person_id FROM (SELECT DISTINCT cohortpeople.person_id AS person_id, cohortpeople.cohort_id AS cohort_id FROM cohortpeople WHERE and(equals(cohortpeople.team_id, 93), in(tuple(cohortpeople.cohort_id, cohortpeople.version), [(8, 18262), (10024, 3408), (924, 10921), (928, 10916), (13182, 2997), (925, 10897), (5, 19387), (4, 20136), (7, 19391), (6, 19038), (926, 10801), (927, 10900)]))) AS cohort_people WHERE ifNull(equals(cohort_people.cohort_id, 10024), 0)) AS freska_group_cohort)))) AS ranked_events WHERE ifNull(equals(ranked_events.rn, 1), 0) GROUP BY ranked_events.period ORDER BY ranked_events.period ASC LIMIT 1000",
                {"cohortpeople"},
                set(),
            ),
        ]
    )
    def test_list_team_id_filters(
        self,
        query: str,
        expected_with_team_id: set[str],
        expected_without_team_id: set[str],
    ) -> None:
        parsed = parse_select(query)
        result = list_team_id_filters(parsed)

        self.assertEqual(result.with_team_id, expected_with_team_id)
        self.assertEqual(result.without_team_id, expected_without_team_id)
