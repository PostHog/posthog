from posthog.hogql import ast
from posthog.hogql.visitor import CloningVisitor


class PreAggregatedPropertyTransformer(CloningVisitor):
    """Transforms property field chains to match pre-aggregated table column names"""

    def __init__(self, table_name: str, supported_props_filters: dict):
        super().__init__()
        self.table_name = table_name
        self.supported_props_filters = supported_props_filters

    def visit_field(self, node: ast.Field) -> ast.Field:
        if len(node.chain) >= 2:
            if node.chain[:2] == ["events", "properties"] and len(node.chain) == 3:
                prop_key = node.chain[2]
                if prop_key in self.supported_props_filters:
                    return ast.Field(chain=[self.table_name, self.supported_props_filters[prop_key]])

            elif node.chain[:2] == ["person", "properties"] and len(node.chain) == 3:
                prop_key = node.chain[2]
                if prop_key in self.supported_props_filters:
                    return ast.Field(chain=[self.table_name, self.supported_props_filters[prop_key]])

            elif node.chain[0] == "session" and len(node.chain) == 2:
                prop_key = node.chain[1]
                if prop_key in self.supported_props_filters:
                    return ast.Field(chain=[self.table_name, self.supported_props_filters[prop_key]])

            elif node.chain[0] == "properties" and len(node.chain) == 2:
                prop_key = node.chain[1]
                if prop_key in self.supported_props_filters:
                    return ast.Field(chain=[self.table_name, self.supported_props_filters[prop_key]])

        return super().visit_field(node)
