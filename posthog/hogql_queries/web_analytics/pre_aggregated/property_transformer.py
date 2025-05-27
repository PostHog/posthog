from posthog.hogql import ast
from posthog.hogql.visitor import CloningVisitor


class PreAggregatedPropertyTransformer(CloningVisitor):
    """Transforms field chains to reference pre-aggregated table columns."""

    def __init__(self, table_name: str, supported_props_filters: dict):
        super().__init__()
        self.table_name = table_name
        self.supported_props_filters = supported_props_filters

    def visit_field(self, node: ast.Field) -> ast.Field:
        chain = node.chain

        prop_key = None
        if chain[:2] == ["events", "properties"] and len(chain) == 3:
            prop_key = chain[2]
        elif (chain[:1] == ["session"] or chain[:1] == ["properties"]) and len(chain) == 2:
            prop_key = chain[1]

        if prop_key and prop_key in self.supported_props_filters:
            return ast.Field(chain=[self.table_name, self.supported_props_filters[prop_key]])

        return super().visit_field(node)
