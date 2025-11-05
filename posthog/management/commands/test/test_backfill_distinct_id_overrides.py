import uuid
import operator

from posthog.test.base import BaseTest, ClickhouseTestMixin

from posthog.clickhouse.client.execute import sync_execute
from posthog.management.commands.backfill_distinct_id_overrides import Backfill


class ExecuteBackfillTestCase(ClickhouseTestMixin, BaseTest):
    def __run_test_backfill(self, dry_run: bool) -> None:
        distinct_id = "override-me"

        rows_for_distinct_id = [
            {"team_id": self.team.id, "distinct_id": distinct_id, "person_id": uuid.uuid4(), "version": version}
            for version in range(3)
        ]

        # never were overridden (version = 0), so no overrides should be created
        rows_to_ignore = [
            {"team_id": self.team.id, "distinct_id": f"ignore-me/{i}", "person_id": uuid.uuid4(), "version": 0}
            for i in range(5)
        ]

        sync_execute(
            "INSERT INTO person_distinct_id2 (team_id, distinct_id, person_id, version) VALUES",
            [*rows_for_distinct_id, *rows_to_ignore],
        )

        # nothing should be in the override table yet
        assert sync_execute(
            "SELECT count() FROM person_distinct_id_overrides WHERE team_id = %(team_id)s",
            {"team_id": self.team.id},
        ) == [(0,)]

        Backfill(self.team.id).execute(dry_run=dry_run)

        read_columns = ["team_id", "distinct_id", "person_id", "version"]
        distinct_id_override_rows = sync_execute(
            f"""
                SELECT {', '.join(read_columns)}
                FROM person_distinct_id_overrides
                WHERE team_id = %(team_id)s
            """,
            {"team_id": self.team.id},
        )

        if not dry_run:
            assert distinct_id_override_rows == [operator.itemgetter(*read_columns)(rows_for_distinct_id[-1])]
        else:
            assert distinct_id_override_rows == []

    def test_execute_backfill(self) -> None:
        self.__run_test_backfill(dry_run=False)

    def test_execute_backfill_dry_run(self) -> None:
        self.__run_test_backfill(dry_run=True)
