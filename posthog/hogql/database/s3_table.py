from typing import Dict, Optional

from posthog.hogql.database.models import FunctionCallTable, DatabaseField
from posthog.hogql.escape_sql import escape_hogql_identifier


class S3Table(FunctionCallTable):
    url: str
    fields: Dict[str, DatabaseField]
    format: str = "CSVWithNames"
    access_key: Optional[str] = None
    access_secret: Optional[str] = None

    def has_field(self, name: str) -> bool:
        return name in self.fields

    def get_field(self, name: str) -> DatabaseField:
        if self.has_field(name):
            return self.fields[name]
        raise Exception(f'Field "{name}" not found on table {self.__class__.__name__}')

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

    def get_asterisk(self):
        return {key: self.get_field(key) for key in self.fields}
