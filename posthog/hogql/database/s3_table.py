from typing import Optional

from posthog.hogql.database.models import FunctionCallTable
from posthog.hogql.escape_sql import escape_hogql_identifier


class S3Table(FunctionCallTable):
    url: str
    format: str = "CSVWithNames"
    access_key: Optional[str] = None
    access_secret: Optional[str] = None

    def to_printed_hogql(self):
        return escape_hogql_identifier(self.name)

    def to_printed_clickhouse(self, context):
        escaped_url = context.add_value(self.url)
        escaped_format = context.add_value(self.format)

        if self.access_key and self.access_secret:
            escaped_access_key = context.add_value(self.access_key)
            escaped_access_secret = context.add_value(self.access_secret)

            return (
                f"s3Cluster('posthog', {escaped_url}, {escaped_access_key}, {escaped_access_secret}, {escaped_format})"
            )
        return f"s3Cluster('posthog', {escaped_url}, {escaped_format})"
