from posthog.hogql import ast

# HogQL functions whose definition is a Python AST builder expanded by the printer's visit_call to real
# SQL, so the catalog holds a single node and the big expression only materializes for queries that use
# it. None of these map to a real ClickHouse function. Builder imports are lazy to avoid a printer->schema
# cycle and to keep the heavy bot-definitions import off the printer's load path.


def maybe_expand_printer_only_function(node: ast.Call) -> ast.Expr | None:
    name = node.name
    if name == "_defaultChannelType":
        from posthog.hogql.database.schema.channel_type import expand_default_channel_type_call  # noqa: PLC0415

        return expand_default_channel_type_call(node.args)
    if name == "_initialDomainType":
        from posthog.hogql.database.schema.channel_type import expand_initial_domain_type_call  # noqa: PLC0415

        return expand_initial_domain_type_call(node.args)
    if name.startswith("__preview_"):
        from posthog.hogql.functions.traffic_type import TRAFFIC_TYPE_PRINTER_BUILDERS  # noqa: PLC0415

        builder = TRAFFIC_TYPE_PRINTER_BUILDERS.get(name)
        if builder is not None:
            return builder(node, node.args)
    return None
