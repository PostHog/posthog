from posthog.hogql.printer.base import BasePrinter


class HogQLPrinter(BasePrinter):
    """Prints a HogQL AST back out as HogQL text.

    This is the ``dialect="hogql"`` output path — it preserves HogQL-native
    syntax (nullish access, cohort ops, placeholder arguments) rather than
    lowering the tree to a target SQL dialect.
    """

    pass
