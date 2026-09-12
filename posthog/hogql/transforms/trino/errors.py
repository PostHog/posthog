from posthog.hogql import ast
from posthog.hogql.errors import QueryError


class TrinoLoweringError(QueryError):
    code_name = "hogql_trino_unsupported"

    def __init__(
        self,
        feature_code: str,
        construct: str,
        node: ast.Expr | None = None,
        *,
        detail: str | None = None,
    ) -> None:
        super().__init__(
            f"[{feature_code}] {detail or f'{construct} is not supported by the Trino backend.'}", node=node
        )
        self.feature_code = feature_code
        self.construct = construct
