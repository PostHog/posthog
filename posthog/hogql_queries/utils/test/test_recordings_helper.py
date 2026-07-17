from unittest import TestCase
from unittest.mock import MagicMock, patch

from posthog.hogql_queries.utils.recordings_helper import SESSION_ID_BATCH_SIZE, RecordingsHelper


class TestRecordingsHelper(TestCase):
    def _helper(self) -> RecordingsHelper:
        team = MagicMock()
        team.id = 1
        return RecordingsHelper(team=team)

    @patch("posthog.hogql_queries.utils.recordings_helper.execute_hogql_query")
    def test_batches_session_ids_and_unions_results(self, mock_execute: MagicMock) -> None:
        # Two batches worth of session IDs plus one, so the third batch has a single ID.
        session_ids = [f"session-{i}" for i in range(SESSION_ID_BATCH_SIZE * 2 + 1)]

        # Each query echoes back the IDs it was asked about, so we can assert the union is complete
        # and that no single query received more than one batch of IDs.
        def fake_execute(query, placeholders, team, user):  # type: ignore[no-untyped-def]
            in_array = placeholders["where_predicates"].right
            returned_ids = [const.value for const in in_array.exprs]
            assert len(returned_ids) <= SESSION_ID_BATCH_SIZE
            response = MagicMock()
            response.results = [(sid,) for sid in returned_ids]
            return response

        mock_execute.side_effect = fake_execute

        result = self._helper()._matching_clickhouse_recordings(session_ids)

        assert mock_execute.call_count == 3
        assert result == set(session_ids)

    @patch("posthog.hogql_queries.utils.recordings_helper.execute_hogql_query")
    def test_empty_input_does_not_query(self, mock_execute: MagicMock) -> None:
        result = self._helper()._matching_clickhouse_recordings([])

        assert result == set()
        mock_execute.assert_not_called()
