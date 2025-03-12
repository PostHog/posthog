from posthog.hogql.errors import QueryError
from posthog.hogql.query import execute_hogql_query
from posthog.test.base import BaseTest


class TestRecordingButton(BaseTest):
    def test_recording_button(self):
        response = execute_hogql_query("select recording_button('12345-6789') from events", self.team, pretty=False)
        # self.assertEqual(
        #     response.clickhouse,
        #     f"SELECT tuple(%(hogql_val_0)s, %(hogql_val_1)s, %(hogql_val_2)s, %(hogql_val_3)s, %(hogql_val_4)s, replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_5)s), ''), 'null'), '^"
        #     | "$', '')) FROM events WHERE equals(events.team_id, 221) LIMIT 100 SETTINGS readonly=2, max_execution_time=60, allow_experimental_object_type=1, format_csv_allow_double_quotes=0, max_ast_elements=4000000, max_expanded_ast_elements=4000000, max_bytes_before_external_group_by=0",
        # )
        # self.assertEqual(
        #     response.hogql,
        #     f"SELECT tuple('__hx_tag', 'RecordingButton', 'sessionId', '12345-6789', 'recordingStatus', 'sql(properties.$current_url)') LIMIT 100",
        # )
        self.assertEqual(
            response.results,
            (
                "__hx_tag",
                "RecordingButton",
                "sessionId",
                "12345-6789",
                "recordingStatus",
                "sql(properties.$current_url)",
            ),
        )

    def test_recording_button_error(self):
        with self.assertRaises(QueryError) as e:
            execute_hogql_query(f"SELECT recording_button()", self.team)
        self.assertEqual(str(e.exception), "Function 'recording_button' expects 1 argument, found 0")
