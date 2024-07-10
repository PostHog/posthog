from typing import Optional

from posthog.hogql.database.models import FunctionCallTable
from posthog.hogql.escape_sql import escape_hogql_identifier
from posthog.hogql.errors import NotImplementedError


class S3Table(FunctionCallTable):
    url: str
    format: str = "CSVWithNames"
    access_key: Optional[str] = None
    access_secret: Optional[str] = None
    structure: Optional[str] = None

    def to_printed_hogql(self):
        return escape_hogql_identifier(self.name)

    def to_printed_clickhouse(self, context):
        if self.format == "Delta":
            escaped_url = context.add_sensitive_value(self.url)
            escaped_structure = context.add_value(self.structure)

            expr = f"deltaLake({escaped_url}"

            if self.access_key and self.access_secret:
                escaped_access_key = context.add_sensitive_value(self.access_key)
                escaped_access_secret = context.add_sensitive_value(self.access_secret)

                expr += f", {escaped_access_key}, {escaped_access_secret}"

            if self.structure:
                expr += f", {escaped_structure}"

            return f"{expr})"

        escaped_url = context.add_sensitive_value(self.url)
        escaped_format = context.add_value(self.format)
        escaped_structure = context.add_value(self.structure)

        expr = f"s3({escaped_url}"

        if self.access_key and self.access_secret:
            escaped_access_key = context.add_sensitive_value(self.access_key)
            escaped_access_secret = context.add_sensitive_value(self.access_secret)

            expr += f", {escaped_access_key}, {escaped_access_secret}"

        expr += f", {escaped_format}"

        if self.structure:
            expr += f", {escaped_structure}"

        return f"{expr})"

        raise NotImplementedError(f'Format "{self.format}" is not supported in S3 tables')
