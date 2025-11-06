from posthog.test.base import BaseTest

from posthog.hogql.errors import QueryError
from posthog.hogql.query import execute_hogql_query


class TestRecordingButton(BaseTest):
    def test_recording_button(self):
        response = execute_hogql_query("select recordingButton('12345-6789', 'active')", self.team, pretty=False)
        self.assertEqual(
            response.clickhouse,
            f"SELECT tuple(%(hogql_val_0)s, %(hogql_val_1)s, %(hogql_val_2)s, %(hogql_val_3)s, %(hogql_val_4)s, %(hogql_val_5)s) LIMIT 100 SETTINGS readonly=2, max_execution_time=60, allow_experimental_object_type=1, format_csv_allow_double_quotes=0, output_format_json_quote_64bit_integers=1, max_ast_elements=4000000, max_expanded_ast_elements=4000000, max_bytes_before_external_group_by=0, transform_null_in=1, optimize_min_equality_disjunction_chain_length=4294967295, allow_experimental_join_condition=1",
        )
        self.assertEqual(
            response.hogql,
            f"SELECT tuple('__hx_tag', 'RecordingButton', 'sessionId', '12345-6789', 'recordingStatus', 'active') LIMIT 100",
        )
        self.assertEqual(
            response.results[0][0],
            ("__hx_tag", "RecordingButton", "sessionId", "12345-6789", "recordingStatus", "active"),
        )

    def test_recording_button_error(self):
        with self.assertRaises(QueryError) as e:
            execute_hogql_query(f"SELECT recordingButton()", self.team)
        self.assertEqual(str(e.exception), "Function 'recordingButton' expects at least 1 argument, found 0")
