import itertools
import uuid
from unittest import mock

from clickhouse_driver.client import Client
from clickhouse_driver.errors import ErrorCodes, ServerException
from posthog.client import sync_execute
from posthog.management.commands.backfill_distinct_id_overrides import BackfillQuery, execute_backfill
from posthog.models.person.util import create_person_distinct_id
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events


class ExecuteBackfillTestCase(ClickhouseTestMixin, BaseTest):
    def __run_test_backfill(self, dry_run: bool) -> None:
        distinct_ids_to_person_id = {
            "no-override": uuid.uuid4(),
            "needs-override": uuid.uuid4(),
        }

        for _ in range(3):
            _create_event(
                team=self.team,
                event="invalid",
                distinct_id="no-override",
                person_id=distinct_ids_to_person_id["no-override"],  # keep correct person id
            )

        for _ in range(3):
            _create_event(
                team=self.team,
                event="invalid",
                distinct_id="needs-override",
                person_id=str(uuid.uuid4()),  # mismatched value causes a backfill row
            )

        flush_persons_and_events()

        for distinct_id, person_id in distinct_ids_to_person_id.items():
            create_person_distinct_id(
                team_id=self.team.pk,
                distinct_id=distinct_id,
                person_id=str(person_id),
                version=1,
            )

        execute_backfill(BackfillQuery(self.team.id), dry_run=dry_run)

        backfill_rows = sync_execute(
            """
                SELECT distinct_id, person_id, version
                FROM person_distinct_id_overrides
                WHERE team_id = %(team_id)s
            """,
            {"team_id": self.team.id},
        )

        assert backfill_rows == (
            [("needs-override", distinct_ids_to_person_id["needs-override"], -1)] if not dry_run else []
        )

    def test_execute_backfill(self) -> None:
        self.__run_test_backfill(dry_run=False)

    def test_execute_backfill_dry_run(self) -> None:
        self.__run_test_backfill(dry_run=True)

    def test_execute_backfill_split_query(self) -> None:
        with mock.patch.object(Client, "execute") as mock_execute:
            mock_execute.side_effect = itertools.chain(
                [ServerException("(error)", code=ErrorCodes.TOO_MANY_ROWS)],
                itertools.repeat(mock.DEFAULT),
            )
            execute_backfill(BackfillQuery(self.team.id))
            assert mock_execute.call_count == 3  # initial query (error), then two queries after splitting
