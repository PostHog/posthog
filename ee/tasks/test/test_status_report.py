from ee.clickhouse.models.person import create_person_distinct_id
from posthog.client import sync_execute
from posthog.models.utils import UUIDT
from posthog.tasks.status_report import status_report
from posthog.tasks.test.test_status_report import factory_status_report
from posthog.test.base import _create_event, _create_person


class TestStatusReport(factory_status_report(_create_event, _create_person)):  # type: ignore
    # CH only
    def test_status_report_duplicate_distinct_ids(self) -> None:
        create_person_distinct_id(self.team.id, "duplicate_id1", str(UUIDT()))
        create_person_distinct_id(self.team.id, "duplicate_id1", str(UUIDT()))
        create_person_distinct_id(self.team.id, "duplicate_id2", str(UUIDT()))
        create_person_distinct_id(self.team.id, "duplicate_id2", str(UUIDT()))
        create_person_distinct_id(self.team.id, "duplicate_id2", str(UUIDT()))

        for index in range(0, 2):
            sync_execute(
                "INSERT INTO person_distinct_id SELECT %(distinct_id)s, %(person_id)s, %(team_id)s, 1, %(timestamp)s, 0 VALUES",
                {
                    "distinct_id": "duplicate_id_old",
                    "person_id": str(UUIDT()),
                    "team_id": self.team.id,
                    "timestamp": "2020-01-01 12:01:0%s" % index,
                },
            )

        report = status_report(dry_run=True).get("teams")[self.team.id]  # type: ignore

        duplicate_ids_report = report["duplicate_distinct_ids"]

        expected_result = {
            "prev_total_ids_with_duplicates": 1,
            "prev_total_extra_distinct_id_rows": 1,
            "new_total_ids_with_duplicates": 2,
            "new_total_extra_distinct_id_rows": 4,
        }

        self.assertEqual(duplicate_ids_report, expected_result)

    # CH only
    def test_status_report_multiple_ids_per_person(self) -> None:
        person_id1 = str(UUIDT())
        person_id2 = str(UUIDT())

        create_person_distinct_id(self.team.id, "id1", person_id1)
        create_person_distinct_id(self.team.id, "id2", person_id1)
        create_person_distinct_id(self.team.id, "id3", person_id1)
        create_person_distinct_id(self.team.id, "id4", person_id1)
        create_person_distinct_id(self.team.id, "id5", person_id1)

        create_person_distinct_id(self.team.id, "id6", person_id2)
        create_person_distinct_id(self.team.id, "id7", person_id2)
        create_person_distinct_id(self.team.id, "id8", person_id2)

        report = status_report(dry_run=True).get("teams")[self.team.id]  # type: ignore

        multiple_ids_report = report["multiple_ids_per_person"]

        expected_result = {
            "total_persons_with_more_than_2_ids": 2,
            "max_distinct_ids_for_one_person": 5,
        }

        self.assertEqual(multiple_ids_report, expected_result)
