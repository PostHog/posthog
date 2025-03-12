from posthog.hogql.errors import QueryError
from posthog.hogql.query import execute_hogql_query
from posthog.test.base import BaseTest


class TestRecordingButton(BaseTest):
    def test_recording_button(self):
        response = execute_hogql_query(
            """
            select recording_button('12345-6789') from (SELECT '{"$recording_status":"active"}' AS properties)
            """,
            self.team,
            pretty=False,
        )
        self.assertEqual(
            response.hogql,
            f"SELECT tuple('__hx_tag', 'RecordingButton', 'sessionId', '12345-6789', 'recordingStatus', 'sql(properties.$recording_status)') LIMIT 100",
        )
        self.assertEqual(
            response.results,
            (
                "__hx_tag",
                "RecordingButton",
                "sessionId",
                "12345-6789",
                "recordingStatus",
                "sql(properties.$recording_status)",
            ),
        )

    def test_recording_button_error(self):
        with self.assertRaises(QueryError) as e:
            execute_hogql_query(f"SELECT recording_button()", self.team)
        self.assertEqual(str(e.exception), "Function 'recording_button' expects 1 argument, found 0")
