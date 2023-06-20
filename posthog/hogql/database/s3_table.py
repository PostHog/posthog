from posthog.hogql.database.models import FunctionCallTable
from posthog.hogql.escape_sql import escape_hogql_identifier


class S3Table(FunctionCallTable):
    url: str
    format: str = "CSVWithNames"

    def to_printed_hogql(self):
        return escape_hogql_identifier(self.name)

    def to_printed_clickhouse(self, context):
        escaped_url = context.add_value(self.url)
        escaped_format = context.add_value(self.format)
        return f"s3({escaped_url}, {escaped_format})"
