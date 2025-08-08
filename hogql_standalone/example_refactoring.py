"""
Example refactoring of existing HogQL code to use dependency injection.
This shows the before/after for removing Django dependencies.
"""

# This is what the BEFORE looks like (from posthog/hogql/functions/cohort.py):
"""
def cohort(node: ast.Expr, args: list[ast.Expr], context: HogQLContext) -> ast.Expr:
    arg = args[0]
    if not isinstance(arg, MockConstant):
        raise QueryError("cohort() takes only constant arguments", node=arg)

    from posthog.models import Cohort  # <-- Django dependency

    if (isinstance(arg.value, int) or isinstance(arg.value, float)) and not isinstance(arg.value, bool):
        # Django ORM query <-- Database dependency
        cohorts1 = Cohort.objects.filter(id=int(arg.value), team__project_id=context.project_id).values_list(
            "id", "is_static", "version", "name"
        )
        if len(cohorts1) == 1:
            context.add_notice(
                start=arg.start,
                end=arg.end,
                message=f"Cohort #{cohorts1[0][0]} can also be specified as {escape_clickhouse_string(cohorts1[0][3])}",
                fix=escape_clickhouse_string(cohorts1[0][3]),
            )
            return cohort_subquery(cohorts1[0][0], cohorts1[0][1], cohorts1[0][2])
        raise QueryError(f"Could not find cohort with ID {arg.value}", node=arg)
"""


# This is what the AFTER would look like:

from typing import Optional
# Since we moved outside posthog package, we can't import hogql directly
# This demonstrates that the standalone version needs its own implementations
# For this example, we'll create mock implementations

class MockASTExpr:
    pass

class MockConstant(MockASTExpr):
    def __init__(self, value):
        self.value = value
        self.start = None
        self.end = None

class QueryError(Exception):
    def __init__(self, message, node=None):
        super().__init__(message)
        self.node = node

def escape_clickhouse_string(s):
    """Mock implementation - in real version this would be copied from hogql"""
    return f"'{s}'"

def parse_expr(sql, placeholders=None, start=None):
    """Mock implementation - in real version this would be copied from hogql"""
    return MockASTExpr()

from context import StandaloneHogQLContext


def cohort_subquery(cohort_id, is_static, version: Optional[int] = None) -> MockASTExpr:
    """This function stays the same - no Django dependencies"""
    if is_static:
        sql = "(SELECT person_id FROM static_cohort_people WHERE cohort_id = {cohort_id})"
    elif version is not None:
        sql = "(SELECT person_id FROM raw_cohort_people WHERE cohort_id = {cohort_id} AND version = {version})"
    else:
        sql = "(SELECT person_id FROM raw_cohort_people WHERE cohort_id = {cohort_id} GROUP BY person_id, cohort_id, version HAVING sum(sign) > 0)"
    return parse_expr(
        sql, {"cohort_id": MockConstant(value=cohort_id), "version": MockConstant(value=version)}, start=None
    )


def cohort_query_node(node: MockASTExpr, context: StandaloneHogQLContext) -> MockASTExpr:
    """Updated to use StandaloneHogQLContext"""
    return cohort(node, [node], context)


def cohort(node: MockASTExpr, args: list[MockASTExpr], context: StandaloneHogQLContext) -> MockASTExpr:
    """
    Refactored version that uses injected cohort data instead of Django ORM.
    No Django dependencies!
    """
    arg = args[0]
    if not isinstance(arg, MockConstant):
        raise QueryError("cohort() takes only constant arguments", node=arg)

    # NO Django import - all data comes from context.data_bundle
    cohorts_data = context.data_bundle.cohorts  # Dict[int, CohortData]

    if (isinstance(arg.value, int) or isinstance(arg.value, float)) and not isinstance(arg.value, bool):
        cohort_id = int(arg.value)
        
        # Look up in injected data instead of database query
        if cohort_id in cohorts_data:
            cohort_data = cohorts_data[cohort_id]
            
            context.add_notice(
                start=arg.start,
                end=arg.end,
                message=f"Cohort #{cohort_data.id} can also be specified as {escape_clickhouse_string(cohort_data.name)}",
                fix=escape_clickhouse_string(cohort_data.name),
            )
            
            # Use the pre-loaded cohort data instead of DB query result
            version = getattr(cohort_data, 'version', None)
            return cohort_subquery(cohort_data.id, cohort_data.is_static, version)
        
        raise QueryError(f"Could not find cohort with ID {arg.value}", node=arg)

    if isinstance(arg.value, str):
        # Look up by name in the injected data
        cohort_name = arg.value
        found_cohort = None
        
        for cohort_data in cohorts_data.values():
            if cohort_data.name == cohort_name:
                found_cohort = cohort_data
                break
        
        if found_cohort:
            version = getattr(found_cohort, 'version', None)
            return cohort_subquery(found_cohort.id, found_cohort.is_static, version)
        
        raise QueryError(f"Could not find cohort with name {cohort_name}", node=arg)

    raise QueryError(f"Cohort specifier must be a cohort ID or cohort name", node=arg)


# Example of what the migration looks like:
def show_migration_example():
    """
    This shows how existing HogQL code gets migrated.
    """
    print("=== BEFORE (Django-dependent) ===")
    print("✗ Imports Django models")
    print("✗ Makes database queries in real-time") 
    print("✗ Tightly coupled to Django ORM")
    print("✗ Cannot run outside Django environment")
    
    print("\n=== AFTER (Standalone) ===")
    print("✓ No Django imports")
    print("✓ Uses pre-loaded data from context") 
    print("✓ Decoupled from Django ORM")
    print("✓ Can run in microservices, WASM, etc.")
    
    print("\n=== Migration Steps ===")
    print("1. Replace `from posthog.models import X` with data from context")
    print("2. Replace `X.objects.filter(...)` with lookups in context.data_bundle")
    print("3. Replace `context: HogQLContext` with `context: StandaloneHogQLContext`")
    print("4. Update imports to use relative paths")
    
    print("\n=== Benefits ===")
    print("• Can extract HogQL to separate service")
    print("• Can run in WebAssembly for client-side execution")
    print("• Better testability (inject mock data)")
    print("• Better performance (no DB queries during parsing)")
    print("• Language-agnostic data format (protobuf, JSON)")


if __name__ == "__main__":
    show_migration_example()