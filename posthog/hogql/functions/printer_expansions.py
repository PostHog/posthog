from posthog.hogql import ast

# HogQL functions whose definition is a Python AST builder expanded by the printer's visit_call to real
# SQL, so the catalog holds a single node and the big expression only materializes for queries that use
# it. None of these map to a real ClickHouse function. (The __preview_* traffic functions are instead
# expanded in the resolver, see Resolver.visit_call.) Builder imports are lazy to avoid a printer->schema
# import cycle.


def maybe_expand_printer_only_function(node: ast.Call) -> ast.Expr | None:
    name = node.name
    if name == "_defaultChannelType":
        from posthog.hogql.database.schema.channel_type import expand_default_channel_type_call  # noqa: PLC0415

        return expand_default_channel_type_call(node.args)
    if name == "_initialDomainType":
        from posthog.hogql.database.schema.channel_type import expand_initial_domain_type_call  # noqa: PLC0415

        return expand_initial_domain_type_call(node.args)
    return None
