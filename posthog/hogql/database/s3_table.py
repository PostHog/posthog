from typing import Optional

from posthog.clickhouse.client.escape import substitute_params
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import FunctionCallTable
from posthog.hogql.escape_sql import escape_hogql_identifier


def build_function_call(
    url: str,
    format: str,
    access_key: Optional[str] = None,
    access_secret: Optional[str] = None,
    structure: Optional[str] = None,
    context: Optional[HogQLContext] = None,
) -> str:
    raw_params: dict[str, str] = {}

    def add_param(value: str, is_sensitive: bool = True) -> str:
        if context is not None:
            if is_sensitive:
                return context.add_sensitive_value(value)
            return context.add_value(value)

        param_name = f"value_{len(raw_params.items())}"
        raw_params[param_name] = value
        return f"%({param_name})s"

    def return_expr(expr: str) -> str:
        if context is not None:
            return f"{expr})"

        return f"{substitute_params(expr, raw_params)})"

    if format == "Delta":
        escaped_url = add_param(url)
        if structure:
            escaped_structure = add_param(structure, False)

        expr = f"deltaLake({escaped_url}"

        if access_key and access_secret:
            escaped_access_key = add_param(access_key)
            escaped_access_secret = add_param(access_secret)

            expr += f", {escaped_access_key}, {escaped_access_secret}"

        if structure:
            expr += f", {escaped_structure}"

        return return_expr(expr)

    escaped_url = add_param(url)
    escaped_format = add_param(format, False)
    if structure:
        escaped_structure = add_param(structure, False)

    expr = f"s3({escaped_url}"

    if access_key and access_secret:
        escaped_access_key = add_param(access_key)
        escaped_access_secret = add_param(access_secret)

        expr += f", {escaped_access_key}, {escaped_access_secret}"

    expr += f", {escaped_format}"

    if structure:
        expr += f", {escaped_structure}"

    return return_expr(expr)


class S3Table(FunctionCallTable):
    url: str
    format: str = "CSVWithNames"
    access_key: Optional[str] = None
    access_secret: Optional[str] = None
    structure: Optional[str] = None

    def to_printed_hogql(self):
        return escape_hogql_identifier(self.name)

    def to_printed_clickhouse(self, context):
        return build_function_call(
            url=self.url,
            format=self.format,
            access_key=self.access_key,
            access_secret=self.access_secret,
            structure=self.structure,
            context=context,
        )
