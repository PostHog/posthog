from typing import Literal, Optional, cast
from collections.abc import Callable

from antlr4 import CommonTokenStream, InputStream, ParseTreeVisitor, ParserRuleContext
from antlr4.error.ErrorListener import ErrorListener
from prometheus_client import Histogram

from posthog.hogql import ast
from posthog.hogql.ast import SelectSetNode
from posthog.hogql.base import AST
from posthog.hogql.constants import RESERVED_KEYWORDS
from posthog.hogql.errors import BaseHogQLError, NotImplementedError, SyntaxError
from posthog.hogql.grammar.HogQLLexer import HogQLLexer
from posthog.hogql.grammar.HogQLParser import HogQLParser
from posthog.hogql.parse_string import parse_string_literal_text, parse_string_literal_ctx, parse_string_text_ctx
from posthog.hogql.placeholders import replace_placeholders
from posthog.hogql.timings import HogQLTimings
from hogql_parser import (
    parse_expr as _parse_expr_cpp,
    parse_order_expr as _parse_order_expr_cpp,
    parse_select as _parse_select_cpp,
    parse_full_template_string as _parse_full_template_string_cpp,
    parse_program as _parse_program_cpp,
)


def safe_lambda(f):
    def wrapped(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except Exception as e:
            if str(e) == "Empty Stack":  # Antlr throws `Exception("Empty Stack")` ¯\_(ツ)_/¯
                raise SyntaxError("Unmatched curly bracket") from e
            raise

    return wrapped


RULE_TO_PARSE_FUNCTION: dict[
    Literal["python", "cpp"], dict[Literal["expr", "order_expr", "select", "full_template_string", "program"], Callable]
] = {
    "python": {
        "expr": safe_lambda(
            lambda string, start: HogQLParseTreeConverter(start=start).visit(get_parser(string).expr())
        ),
        "order_expr": safe_lambda(lambda string: HogQLParseTreeConverter().visit(get_parser(string).orderExpr())),
        "select": safe_lambda(lambda string: HogQLParseTreeConverter().visit(get_parser(string).select())),
        "full_template_string": safe_lambda(
            lambda string: HogQLParseTreeConverter().visit(get_parser(string).fullTemplateString())
        ),
        "program": safe_lambda(lambda string: HogQLParseTreeConverter().visit(get_parser(string).program())),
    },
    "cpp": {
        "expr": lambda string, start: _parse_expr_cpp(string, is_internal=start is None),
        "order_expr": lambda string: _parse_order_expr_cpp(string),
        "select": lambda string: _parse_select_cpp(string),
        "full_template_string": lambda string: _parse_full_template_string_cpp(string),
        "program": lambda string: _parse_program_cpp(string),
    },
}

RULE_TO_HISTOGRAM: dict[Literal["expr", "order_expr", "select", "full_template_string"], Histogram] = {
    cast(Literal["expr", "order_expr", "select", "full_template_string"], rule): Histogram(
        f"parse_{rule}_seconds",
        f"Time to parse {rule} expression",
        labelnames=["backend"],
    )
    for rule in ("expr", "order_expr", "select", "full_template_string")
}


def parse_string_template(
    string: str,
    placeholders: Optional[dict[str, ast.Expr]] = None,
    timings: Optional[HogQLTimings] = None,
    *,
    backend: Literal["python", "cpp"] = "cpp",
) -> ast.Call:
    """Parse a full template string without start/end quotes"""
    if timings is None:
        timings = HogQLTimings()
    with timings.measure(f"parse_full_template_string_{backend}"):
        with RULE_TO_HISTOGRAM["full_template_string"].labels(backend=backend).time():
            node = RULE_TO_PARSE_FUNCTION[backend]["full_template_string"]("F'" + string)
        if placeholders:
            with timings.measure("replace_placeholders"):
                node = replace_placeholders(node, placeholders)
    return node


def parse_expr(
    expr: str,
    placeholders: Optional[dict[str, ast.Expr]] = None,
    start: Optional[int] = 0,
    timings: Optional[HogQLTimings] = None,
    *,
    backend: Literal["python", "cpp"] = "cpp",
) -> ast.Expr:
    if expr == "":
        raise SyntaxError("Empty query")
    if timings is None:
        timings = HogQLTimings()
    with timings.measure(f"parse_expr_{backend}"):
        with RULE_TO_HISTOGRAM["expr"].labels(backend=backend).time():
            node = RULE_TO_PARSE_FUNCTION[backend]["expr"](expr, start)
        if placeholders:
            with timings.measure("replace_placeholders"):
                node = replace_placeholders(node, placeholders)
    return node


def parse_order_expr(
    order_expr: str,
    placeholders: Optional[dict[str, ast.Expr]] = None,
    timings: Optional[HogQLTimings] = None,
    *,
    backend: Literal["python", "cpp"] = "cpp",
) -> ast.OrderExpr:
    if timings is None:
        timings = HogQLTimings()
    with timings.measure(f"parse_order_expr_{backend}"):
        with RULE_TO_HISTOGRAM["order_expr"].labels(backend=backend).time():
            node = RULE_TO_PARSE_FUNCTION[backend]["order_expr"](order_expr)
        if placeholders:
            with timings.measure("replace_placeholders"):
                node = replace_placeholders(node, placeholders)
    return node


def parse_select(
    statement: str,
    placeholders: Optional[dict[str, ast.Expr]] = None,
    timings: Optional[HogQLTimings] = None,
    *,
    backend: Literal["python", "cpp"] = "cpp",
) -> ast.SelectQuery | ast.SelectSetQuery:
    if timings is None:
        timings = HogQLTimings()
    with timings.measure(f"parse_select_{backend}"):
        with RULE_TO_HISTOGRAM["select"].labels(backend=backend).time():
            node = RULE_TO_PARSE_FUNCTION[backend]["select"](statement)
        if placeholders:
            with timings.measure("replace_placeholders"):
                node = replace_placeholders(node, placeholders)
    return node


def parse_program(
    source: str,
    timings: Optional[HogQLTimings] = None,
    *,
    backend: Literal["python", "cpp"] = "cpp",
) -> ast.Program:
    if timings is None:
        timings = HogQLTimings()
    with timings.measure(f"parse_expr_{backend}"):
        with RULE_TO_HISTOGRAM["expr"].labels(backend=backend).time():
            node = RULE_TO_PARSE_FUNCTION[backend]["program"](source)
    return node


def get_parser(query: str) -> HogQLParser:
    input_stream = InputStream(data=query)
    lexer = HogQLLexer(input_stream)
    stream = CommonTokenStream(lexer)
    parser = HogQLParser(stream)
    parser.removeErrorListeners()
    parser.addErrorListener(HogQLErrorListener(query))
    return parser


class HogQLErrorListener(ErrorListener):
    query: str

    def __init__(self, query: str = ""):
        super().__init__()
        self.query = query

    def get_position(self, line, column):
        lines = self.query.split("\n")
        try:
            position = sum(len(lines[i]) + 1 for i in range(line - 1)) + column
        except IndexError:
            return -1
        if position > len(self.query):
            return -1
        return position

    def syntaxError(self, recognizer, offendingType, line, column, msg, e):
        start = max(self.get_position(line, column), 0)
        raise SyntaxError(msg, start=start, end=len(self.query))


class HogQLParseTreeConverter(ParseTreeVisitor):
    def __init__(self, start: Optional[int] = 0):
        super().__init__()
        self.start = start

    def visit(self, ctx: ParserRuleContext):
        start = ctx.start.start if ctx.start else None
        end = ctx.stop.stop + 1 if ctx.stop else None
        try:
            node = super().visit(ctx)
            if isinstance(node, AST) and self.start is not None:
                node.start = start
                node.end = end
            return node
        except BaseHogQLError as e:
            if start is not None and end is not None and e.start is None or e.end is None:
                e.start = start
                e.end = end
            raise

    def visitProgram(self, ctx: HogQLParser.ProgramContext):
        declarations: list[ast.Declaration] = []
        for declaration in ctx.declaration():
            if not declaration.statement() or not declaration.statement().emptyStmt():
                statement = self.visit(declaration)
                declarations.append(cast(ast.Declaration, statement))
        return ast.Program(declarations=declarations)

    def visitDeclaration(self, ctx: HogQLParser.DeclarationContext):
        return self.visitChildren(ctx)

    def visitExpression(self, ctx: HogQLParser.ExpressionContext):
        return self.visitChildren(ctx)

    def visitVarDecl(self, ctx: HogQLParser.VarDeclContext):
        return ast.VariableDeclaration(
            name=ctx.identifier().getText(),
            expr=self.visit(ctx.expression()) if ctx.expression() else None,
        )

    def visitVarAssignment(self, ctx: HogQLParser.VarAssignmentContext):
        return ast.VariableAssignment(
            left=self.visit(ctx.expression(0)),
            right=self.visit(ctx.expression(1)),
        )

    def visitStatement(self, ctx: HogQLParser.StatementContext):
        return self.visitChildren(ctx)

    def visitExprStmt(self, ctx: HogQLParser.ExprStmtContext):
        return ast.ExprStatement(expr=self.visit(ctx.expression()))

    def visitReturnStmt(self, ctx: HogQLParser.ReturnStmtContext):
        return ast.ReturnStatement(expr=self.visit(ctx.expression()) if ctx.expression() else None)

    def visitThrowStmt(self, ctx: HogQLParser.ThrowStmtContext):
        return ast.ThrowStatement(expr=self.visit(ctx.expression()) if ctx.expression() else None)

    def visitCatchBlock(self, ctx: HogQLParser.CatchBlockContext):
        return (
            self.visit(ctx.catchVar) if ctx.catchVar else None,
            self.visit(ctx.catchType) if ctx.catchType else None,
            self.visit(ctx.catchStmt),
        )

    def visitTryCatchStmt(self, ctx: HogQLParser.TryCatchStmtContext):
        return ast.TryCatchStatement(
            try_stmt=self.visit(ctx.tryStmt),
            catches=[self.visit(catch) for catch in ctx.catchBlock()],
            finally_stmt=self.visit(ctx.finallyStmt) if ctx.finallyStmt else None,
        )

    def visitIfStmt(self, ctx: HogQLParser.IfStmtContext):
        return ast.IfStatement(
            expr=self.visit(ctx.expression()),
            then=self.visit(ctx.statement(0)),
            else_=self.visit(ctx.statement(1)) if ctx.statement(1) else None,
        )

    def visitWhileStmt(self, ctx: HogQLParser.WhileStmtContext):
        return ast.WhileStatement(
            expr=self.visit(ctx.expression()),
            body=self.visit(ctx.statement()) if ctx.statement() else None,
        )

    def visitForInStmt(self, ctx: HogQLParser.ForInStmtContext):
        first_identifier = ctx.identifier(0).getText()
        second_identifier = ctx.identifier(1).getText() if ctx.identifier(1) else None
        return ast.ForInStatement(
            valueVar=second_identifier if second_identifier is not None else first_identifier,
            keyVar=first_identifier if second_identifier is not None else None,
            expr=self.visit(ctx.expression()),
            body=self.visit(ctx.statement()),
        )

    def visitForStmt(self, ctx: HogQLParser.ForStmtContext):
        initializer = ctx.initializerVarDeclr or ctx.initializerVarAssignment or ctx.initializerExpression
        increment = ctx.incrementVarDeclr or ctx.incrementVarAssignment or ctx.incrementExpression

        return ast.ForStatement(
            initializer=self.visit(initializer) if initializer else None,
            condition=self.visit(ctx.condition) if ctx.condition else None,
            increment=self.visit(increment) if increment else None,
            body=self.visit(ctx.statement()),
        )

    def visitFuncStmt(self, ctx: HogQLParser.FuncStmtContext):
        return ast.Function(
            name=ctx.identifier().getText(),
            params=self.visit(ctx.identifierList()) if ctx.identifierList() else [],
            body=self.visit(ctx.block()),
        )

    def visitKvPairList(self, ctx: HogQLParser.KvPairListContext):
        return [self.visit(kv) for kv in ctx.kvPair()]

    def visitKvPair(self, ctx: HogQLParser.KvPairContext):
        k, v = ctx.expression()
        return (self.visit(k), self.visit(v))

    def visitIdentifierList(self, ctx: HogQLParser.IdentifierListContext):
        return [ident.getText() for ident in ctx.identifier()]

    def visitEmptyStmt(self, ctx: HogQLParser.EmptyStmtContext):
        return ast.ExprStatement(expr=None)

    def visitBlock(self, ctx: HogQLParser.BlockContext):
        declarations: list[ast.Declaration] = []
        for declaration in ctx.declaration():
            if not declaration.statement() or not declaration.statement().emptyStmt():
                statement = self.visit(declaration)
                declarations.append(cast(ast.Declaration, statement))
        return ast.Block(declarations=declarations)

    ##### HogQL rules

    def visitSelect(self, ctx: HogQLParser.SelectContext):
        return self.visit(ctx.selectSetStmt() or ctx.selectStmt() or ctx.hogqlxTagElement())

    def visitSelectSetStmt(self, ctx: HogQLParser.SelectSetStmtContext):
        select_queries: list[SelectSetNode] = []

        initial_query = self.visit(ctx.selectStmtWithParens())

        for subsequent in ctx.subsequentSelectSetClause():
            if subsequent.UNION() and subsequent.ALL():
                union_type = "UNION ALL"
            elif subsequent.UNION() and subsequent.DISTINCT():
                union_type = "UNION DISTINCT"
            elif subsequent.INTERSECT() and subsequent.DISTINCT():
                union_type = "INTERSECT DISTINCT"
            elif subsequent.INTERSECT():
                union_type = "INTERSECT"
            elif subsequent.EXCEPT():
                union_type = "EXCEPT"
            else:
                raise SyntaxError(
                    "Set operator must be one of UNION ALL, UNION DISTINCT, INTERSECT, INTERSECT DISTINCT, and EXCEPT"
                )
            select_query = self.visit(subsequent.selectStmtWithParens())
            select_queries.append(
                SelectSetNode(select_query=select_query, set_operator=cast(ast.SetOperator, union_type))
            )

        if len(select_queries) == 0:
            return initial_query
        return ast.SelectSetQuery(initial_select_query=initial_query, subsequent_select_queries=select_queries)

    def visitSelectStmtWithParens(self, ctx: HogQLParser.SelectStmtWithParensContext):
        return self.visit(ctx.selectStmt() or ctx.selectSetStmt() or ctx.placeholder())

    def visitSelectStmt(self, ctx: HogQLParser.SelectStmtContext):
        select_query = ast.SelectQuery(
            ctes=self.visit(ctx.withClause()) if ctx.withClause() else None,
            select=self.visit(ctx.columnExprList()) if ctx.columnExprList() else [],
            distinct=True if ctx.DISTINCT() else None,
            select_from=self.visit(ctx.fromClause()) if ctx.fromClause() else None,
            where=self.visit(ctx.whereClause()) if ctx.whereClause() else None,
            prewhere=self.visit(ctx.prewhereClause()) if ctx.prewhereClause() else None,
            having=self.visit(ctx.havingClause()) if ctx.havingClause() else None,
            group_by=self.visit(ctx.groupByClause()) if ctx.groupByClause() else None,
            order_by=self.visit(ctx.orderByClause()) if ctx.orderByClause() else None,
            limit_by=self.visit(ctx.limitByClause()) if ctx.limitByClause() else None,
        )

        if window_clause := ctx.windowClause():
            select_query.window_exprs = {}
            for index, window_expr in enumerate(window_clause.windowExpr()):
                name = self.visit(window_clause.identifier()[index])
                select_query.window_exprs[name] = self.visit(window_expr)

        if limit_and_offset_clause := ctx.limitAndOffsetClause():
            select_query.limit = self.visit(limit_and_offset_clause.columnExpr(0))
            if offset := limit_and_offset_clause.columnExpr(1):
                select_query.offset = self.visit(offset)
            if limit_and_offset_clause.WITH() and limit_and_offset_clause.TIES():
                select_query.limit_with_ties = True
        elif offset_only_clause := ctx.offsetOnlyClause():
            select_query.offset = self.visit(offset_only_clause.columnExpr())

        if ctx.arrayJoinClause():
            array_join_clause = ctx.arrayJoinClause()
            if select_query.select_from is None:
                raise SyntaxError("Using ARRAY JOIN without a FROM clause is not permitted")
            if array_join_clause.LEFT():
                select_query.array_join_op = "LEFT ARRAY JOIN"
            elif array_join_clause.INNER():
                select_query.array_join_op = "INNER ARRAY JOIN"
            else:
                select_query.array_join_op = "ARRAY JOIN"
            select_query.array_join_list = self.visit(array_join_clause.columnExprList())
            if select_query.array_join_list:
                for expr in select_query.array_join_list:
                    if not isinstance(expr, ast.Alias):
                        raise SyntaxError(
                            "ARRAY JOIN arrays must have an alias",
                            start=expr.start,
                            end=expr.end,
                        )

        if ctx.topClause():
            raise NotImplementedError(f"Unsupported: SelectStmt.topClause()")
        if ctx.settingsClause():
            raise NotImplementedError(f"Unsupported: SelectStmt.settingsClause()")

        return select_query

    def visitWithClause(self, ctx: HogQLParser.WithClauseContext):
        return self.visit(ctx.withExprList())

    def visitTopClause(self, ctx: HogQLParser.TopClauseContext):
        raise NotImplementedError(f"Unsupported node: TopClause")

    def visitFromClause(self, ctx: HogQLParser.FromClauseContext):
        return self.visit(ctx.joinExpr())

    def visitArrayJoinClause(self, ctx: HogQLParser.ArrayJoinClauseContext):
        raise NotImplementedError(f"Unsupported node: ArrayJoinClause")

    def visitWindowClause(self, ctx: HogQLParser.WindowClauseContext):
        raise NotImplementedError(f"Unsupported node: WindowClause")

    def visitPrewhereClause(self, ctx: HogQLParser.PrewhereClauseContext):
        return self.visit(ctx.columnExpr())

    def visitWhereClause(self, ctx: HogQLParser.WhereClauseContext):
        return self.visit(ctx.columnExpr())

    def visitGroupByClause(self, ctx: HogQLParser.GroupByClauseContext):
        return self.visit(ctx.columnExprList())

    def visitHavingClause(self, ctx: HogQLParser.HavingClauseContext):
        return self.visit(ctx.columnExpr())

    def visitOrderByClause(self, ctx: HogQLParser.OrderByClauseContext):
        return self.visit(ctx.orderExprList())

    def visitLimitByClause(self, ctx: HogQLParser.LimitByClauseContext):
        limit_expr = self.visit(ctx.limitExpr())

        # If limit_expr is a tuple (n, offset), split it
        if isinstance(limit_expr, tuple) and len(limit_expr) == 2:
            n, offset_value = limit_expr
            return ast.LimitByExpr(n=n, offset_value=offset_value, exprs=self.visit(ctx.columnExprList()))

        # If no offset, just use limit_expr as n
        return ast.LimitByExpr(n=limit_expr, offset_value=None, exprs=self.visit(ctx.columnExprList()))

    def visitLimitExpr(self, ctx: HogQLParser.LimitExprContext):
        # First expression is always the limit value (n)
        n = self.visit(ctx.columnExpr(0))

        # Check if we have an offset (second expression)
        if ctx.columnExpr(1):
            offset_value = self.visit(ctx.columnExpr(1))
            # For "LIMIT a, b" syntax: a is offset, b is limit
            if ctx.COMMA():
                return (offset_value, n)  # Return tuple as (offset, limit)
            # For "LIMIT a OFFSET b" syntax: a is limit, b is offset
            return (n, offset_value)

        return n

    def visitProjectionOrderByClause(self, ctx: HogQLParser.ProjectionOrderByClauseContext):
        raise NotImplementedError(f"Unsupported node: ProjectionOrderByClause")

    def visitLimitAndOffsetClauseClause(self, ctx: HogQLParser.LimitAndOffsetClauseContext):
        raise Exception(f"Parsed as part of SelectStmt, can't parse directly")

    def visitSettingsClause(self, ctx: HogQLParser.SettingsClauseContext):
        raise NotImplementedError(f"Unsupported node: SettingsClause")

    def visitJoinExprOp(self, ctx: HogQLParser.JoinExprOpContext):
        join1: ast.JoinExpr = self.visit(ctx.joinExpr(0))
        join2: ast.JoinExpr = self.visit(ctx.joinExpr(1))

        if ctx.joinOp():
            join2.join_type = f"{self.visit(ctx.joinOp())} JOIN"
        else:
            join2.join_type = "JOIN"
        join2.constraint = self.visit(ctx.joinConstraintClause())

        last_join = join1
        while last_join.next_join is not None:
            last_join = last_join.next_join
        last_join.next_join = join2

        return join1

    def visitJoinExprTable(self, ctx: HogQLParser.JoinExprTableContext):
        sample = None
        if ctx.sampleClause():
            sample = self.visit(ctx.sampleClause())
        table = self.visit(ctx.tableExpr())
        table_final = True if ctx.FINAL() else None
        if isinstance(table, ast.JoinExpr):
            # visitTableExprAlias returns a JoinExpr to pass the alias
            # visitTableExprFunction returns a JoinExpr to pass the args
            table.table_final = table_final
            table.sample = sample
            return table
        return ast.JoinExpr(table=table, table_final=table_final, sample=sample)

    def visitJoinExprParens(self, ctx: HogQLParser.JoinExprParensContext):
        return self.visit(ctx.joinExpr())

    def visitJoinExprCrossOp(self, ctx: HogQLParser.JoinExprCrossOpContext):
        join1: ast.JoinExpr = self.visit(ctx.joinExpr(0))
        join2: ast.JoinExpr = self.visit(ctx.joinExpr(1))
        join2.join_type = "CROSS JOIN"
        last_join = join1
        while last_join.next_join is not None:
            last_join = last_join.next_join
        last_join.next_join = join2
        return join1

    def visitJoinOpInner(self, ctx: HogQLParser.JoinOpInnerContext):
        tokens = []
        if ctx.ALL():
            tokens.append("ALL")
        if ctx.ANY():
            tokens.append("ANY")
        if ctx.ASOF():
            tokens.append("ASOF")
        tokens.append("INNER")
        return " ".join(tokens)

    def visitJoinOpLeftRight(self, ctx: HogQLParser.JoinOpLeftRightContext):
        tokens = []
        if ctx.LEFT():
            tokens.append("LEFT")
        if ctx.RIGHT():
            tokens.append("RIGHT")
        if ctx.OUTER():
            tokens.append("OUTER")
        if ctx.SEMI():
            tokens.append("SEMI")
        if ctx.ALL():
            tokens.append("ALL")
        if ctx.ANTI():
            tokens.append("ANTI")
        if ctx.ANY():
            tokens.append("ANY")
        if ctx.ASOF():
            tokens.append("ASOF")
        return " ".join(tokens)

    def visitJoinOpFull(self, ctx: HogQLParser.JoinOpFullContext):
        tokens = []
        if ctx.FULL():
            tokens.append("FULL")
        if ctx.OUTER():
            tokens.append("OUTER")
        if ctx.ALL():
            tokens.append("ALL")
        if ctx.ANY():
            tokens.append("ANY")
        return " ".join(tokens)

    def visitJoinOpCross(self, ctx: HogQLParser.JoinOpCrossContext):
        raise NotImplementedError(f"Unsupported node: JoinOpCross")

    def visitJoinConstraintClause(self, ctx: HogQLParser.JoinConstraintClauseContext):
        column_expr_list = self.visit(ctx.columnExprList())
        if len(column_expr_list) != 1:
            raise NotImplementedError(f"Unsupported: JOIN ... ON with multiple expressions")
        return ast.JoinConstraint(expr=column_expr_list[0], constraint_type="USING" if ctx.USING() else "ON")

    def visitSampleClause(self, ctx: HogQLParser.SampleClauseContext):
        ratio_expressions = ctx.ratioExpr()

        sample_ratio_expr = self.visit(ratio_expressions[0])
        offset_ratio_expr = self.visit(ratio_expressions[1]) if len(ratio_expressions) > 1 and ctx.OFFSET() else None

        return ast.SampleExpr(sample_value=sample_ratio_expr, offset_value=offset_ratio_expr)

    def visitOrderExprList(self, ctx: HogQLParser.OrderExprListContext):
        return [self.visit(expr) for expr in ctx.orderExpr()]

    def visitOrderExpr(self, ctx: HogQLParser.OrderExprContext):
        order = "DESC" if ctx.DESC() or ctx.DESCENDING() else "ASC"
        return ast.OrderExpr(expr=self.visit(ctx.columnExpr()), order=cast(Literal["ASC", "DESC"], order))

    def visitRatioExpr(self, ctx: HogQLParser.RatioExprContext):
        if ctx.placeholder():
            return self.visit(ctx.placeholder())

        number_literals = ctx.numberLiteral()

        left = number_literals[0]
        right = number_literals[1] if ctx.SLASH() and len(number_literals) > 1 else None

        return ast.RatioExpr(
            left=self.visitNumberLiteral(left),
            right=self.visitNumberLiteral(right) if right else None,
        )

    def visitSettingExprList(self, ctx: HogQLParser.SettingExprListContext):
        raise NotImplementedError(f"Unsupported node: SettingExprList")

    def visitSettingExpr(self, ctx: HogQLParser.SettingExprContext):
        raise NotImplementedError(f"Unsupported node: SettingExpr")

    def visitWindowExpr(self, ctx: HogQLParser.WindowExprContext):
        frame = ctx.winFrameClause()
        visited_frame = self.visit(frame) if frame else None
        expr = ast.WindowExpr(
            partition_by=self.visit(ctx.winPartitionByClause()) if ctx.winPartitionByClause() else None,
            order_by=self.visit(ctx.winOrderByClause()) if ctx.winOrderByClause() else None,
            frame_method="RANGE" if frame and frame.RANGE() else "ROWS" if frame and frame.ROWS() else None,
            frame_start=visited_frame[0] if isinstance(visited_frame, tuple) else visited_frame,
            frame_end=visited_frame[1] if isinstance(visited_frame, tuple) else None,
        )
        return expr

    def visitWinPartitionByClause(self, ctx: HogQLParser.WinPartitionByClauseContext):
        return self.visit(ctx.columnExprList())

    def visitWinOrderByClause(self, ctx: HogQLParser.WinOrderByClauseContext):
        return self.visit(ctx.orderExprList())

    def visitWinFrameClause(self, ctx: HogQLParser.WinFrameClauseContext):
        return self.visit(ctx.winFrameExtend())

    def visitFrameStart(self, ctx: HogQLParser.FrameStartContext):
        return self.visit(ctx.winFrameBound())

    def visitFrameBetween(self, ctx: HogQLParser.FrameBetweenContext):
        return (self.visit(ctx.winFrameBound(0)), self.visit(ctx.winFrameBound(1)))

    def visitWinFrameBound(self, ctx: HogQLParser.WinFrameBoundContext):
        if ctx.PRECEDING():
            return ast.WindowFrameExpr(
                frame_type="PRECEDING",
                frame_value=self.visit(ctx.numberLiteral()).value if ctx.numberLiteral() else None,
            )
        if ctx.FOLLOWING():
            return ast.WindowFrameExpr(
                frame_type="FOLLOWING",
                frame_value=self.visit(ctx.numberLiteral()).value if ctx.numberLiteral() else None,
            )
        return ast.WindowFrameExpr(frame_type="CURRENT ROW")

    def visitExpr(self, ctx: HogQLParser.ExprContext):
        return self.visit(ctx.columnExpr())

    def visitColumnTypeExprSimple(self, ctx: HogQLParser.ColumnTypeExprSimpleContext):
        raise NotImplementedError(f"Unsupported node: ColumnTypeExprSimple")

    def visitColumnTypeExprNested(self, ctx: HogQLParser.ColumnTypeExprNestedContext):
        raise NotImplementedError(f"Unsupported node: ColumnTypeExprNested")

    def visitColumnTypeExprEnum(self, ctx: HogQLParser.ColumnTypeExprEnumContext):
        raise NotImplementedError(f"Unsupported node: ColumnTypeExprEnum")

    def visitColumnTypeExprComplex(self, ctx: HogQLParser.ColumnTypeExprComplexContext):
        raise NotImplementedError(f"Unsupported node: ColumnTypeExprComplex")

    def visitColumnTypeExprParam(self, ctx: HogQLParser.ColumnTypeExprParamContext):
        raise NotImplementedError(f"Unsupported node: ColumnTypeExprParam")

    def visitColumnExprList(self, ctx: HogQLParser.ColumnExprListContext):
        return [self.visit(c) for c in ctx.columnExpr()]

    def visitColumnExprTernaryOp(self, ctx: HogQLParser.ColumnExprTernaryOpContext):
        return ast.Call(
            name="if",
            args=[
                self.visit(ctx.columnExpr(0)),
                self.visit(ctx.columnExpr(1)),
                self.visit(ctx.columnExpr(2)),
            ],
        )

    def visitColumnExprAlias(self, ctx: HogQLParser.ColumnExprAliasContext):
        alias: str
        if ctx.identifier():
            alias = self.visit(ctx.identifier())
        elif ctx.STRING_LITERAL():
            alias = parse_string_literal_ctx(ctx.STRING_LITERAL())
        else:
            raise SyntaxError(f"Must specify an alias")
        expr = self.visit(ctx.columnExpr())

        if alias.lower() in RESERVED_KEYWORDS:
            raise SyntaxError(f'"{alias}" cannot be an alias or identifier, as it\'s a reserved keyword')

        return ast.Alias(expr=expr, alias=alias)

    def visitColumnExprNegate(self, ctx: HogQLParser.ColumnExprNegateContext):
        return ast.ArithmeticOperation(
            op=ast.ArithmeticOperationOp.Sub,
            left=ast.Constant(value=0),
            right=self.visit(ctx.columnExpr()),
        )

    def visitColumnExprDict(self, ctx: HogQLParser.ColumnExprDictContext):
        return ast.Dict(items=self.visit(ctx.kvPairList()) if ctx.kvPairList() else [])

    def visitColumnExprSubquery(self, ctx: HogQLParser.ColumnExprSubqueryContext):
        return self.visit(ctx.selectSetStmt())

    def visitColumnExprLiteral(self, ctx: HogQLParser.ColumnExprLiteralContext):
        return self.visitChildren(ctx)

    def visitColumnExprArray(self, ctx: HogQLParser.ColumnExprArrayContext):
        return ast.Array(exprs=self.visit(ctx.columnExprList()) if ctx.columnExprList() else [])

    def visitColumnExprSubstring(self, ctx: HogQLParser.ColumnExprSubstringContext):
        raise NotImplementedError(f"Unsupported node: ColumnExprSubstring")

    def visitColumnExprCast(self, ctx: HogQLParser.ColumnExprCastContext):
        raise NotImplementedError(f"Unsupported node: ColumnExprCast")

    def visitColumnExprPrecedence1(self, ctx: HogQLParser.ColumnExprPrecedence1Context):
        if ctx.SLASH():
            op = ast.ArithmeticOperationOp.Div
        elif ctx.ASTERISK():
            op = ast.ArithmeticOperationOp.Mult
        elif ctx.PERCENT():
            op = ast.ArithmeticOperationOp.Mod
        else:
            raise NotImplementedError(f"Unsupported ColumnExprPrecedence1: {ctx.getText()}")
        left = self.visit(ctx.left)
        right = self.visit(ctx.right)
        return ast.ArithmeticOperation(left=left, right=right, op=op)

    def visitColumnExprPrecedence2(self, ctx: HogQLParser.ColumnExprPrecedence2Context):
        left = self.visit(ctx.left)
        right = self.visit(ctx.right)

        if ctx.PLUS():
            return ast.ArithmeticOperation(left=left, right=right, op=ast.ArithmeticOperationOp.Add)
        elif ctx.DASH():
            return ast.ArithmeticOperation(left=left, right=right, op=ast.ArithmeticOperationOp.Sub)
        elif ctx.CONCAT():
            args = []
            if isinstance(left, ast.Call) and left.name == "concat":
                args.extend(left.args)
            else:
                args.append(left)

            if isinstance(right, ast.Call) and right.name == "concat":
                args.extend(right.args)
            else:
                args.append(right)

            return ast.Call(name="concat", args=args)
        else:
            raise NotImplementedError(f"Unsupported ColumnExprPrecedence2: {ctx.getText()}")

    def visitColumnExprPrecedence3(self, ctx: HogQLParser.ColumnExprPrecedence3Context):
        left = self.visit(ctx.left)
        right = self.visit(ctx.right)

        if ctx.EQ_SINGLE() or ctx.EQ_DOUBLE():
            op = ast.CompareOperationOp.Eq
        elif ctx.NOT_EQ():
            op = ast.CompareOperationOp.NotEq
        elif ctx.LT():
            op = ast.CompareOperationOp.Lt
        elif ctx.LT_EQ():
            op = ast.CompareOperationOp.LtEq
        elif ctx.GT():
            op = ast.CompareOperationOp.Gt
        elif ctx.GT_EQ():
            op = ast.CompareOperationOp.GtEq
        elif ctx.LIKE():
            if ctx.NOT():
                op = ast.CompareOperationOp.NotLike
            else:
                op = ast.CompareOperationOp.Like
        elif ctx.ILIKE():
            if ctx.NOT():
                op = ast.CompareOperationOp.NotILike
            else:
                op = ast.CompareOperationOp.ILike
        elif ctx.REGEX_SINGLE() or ctx.REGEX_DOUBLE():
            op = ast.CompareOperationOp.Regex
        elif ctx.NOT_REGEX():
            op = ast.CompareOperationOp.NotRegex
        elif ctx.IREGEX_SINGLE() or ctx.IREGEX_DOUBLE():
            op = ast.CompareOperationOp.IRegex
        elif ctx.NOT_IREGEX():
            op = ast.CompareOperationOp.NotIRegex
        elif ctx.IN():
            if ctx.COHORT():
                if ctx.NOT():
                    op = ast.CompareOperationOp.NotInCohort
                else:
                    op = ast.CompareOperationOp.InCohort
            else:
                if ctx.NOT():
                    op = ast.CompareOperationOp.NotIn
                else:
                    op = ast.CompareOperationOp.In
        else:
            raise NotImplementedError(f"Unsupported ColumnExprPrecedence3: {ctx.getText()}")

        return ast.CompareOperation(left=left, right=right, op=op)

    def visitColumnExprInterval(self, ctx: HogQLParser.ColumnExprIntervalContext):
        if ctx.interval().SECOND():
            name = "toIntervalSecond"
        elif ctx.interval().MINUTE():
            name = "toIntervalMinute"
        elif ctx.interval().HOUR():
            name = "toIntervalHour"
        elif ctx.interval().DAY():
            name = "toIntervalDay"
        elif ctx.interval().WEEK():
            name = "toIntervalWeek"
        elif ctx.interval().MONTH():
            name = "toIntervalMonth"
        elif ctx.interval().QUARTER():
            name = "toIntervalQuarter"
        elif ctx.interval().YEAR():
            name = "toIntervalYear"
        else:
            raise NotImplementedError(f"Unsupported interval type: {ctx.interval().getText()}")

        return ast.Call(name=name, args=[self.visit(ctx.columnExpr())])

    def visitColumnExprIntervalString(self, ctx: HogQLParser.ColumnExprIntervalStringContext):
        if ctx.STRING_LITERAL():
            text = parse_string_literal_ctx(ctx.STRING_LITERAL())
        else:
            raise NotImplementedError(f"Unsupported interval type: {ctx.STRING_LITERAL()}")

        count, unit = text.split(" ")
        if count.isdigit():
            int_count = int(count)
        else:
            raise NotImplementedError(f"Unsupported interval count: {count}")

        if unit == "second" or unit == "seconds":
            name = "toIntervalSecond"
        elif unit == "minute" or unit == "minutes":
            name = "toIntervalMinute"
        elif unit == "hour" or unit == "hours":
            name = "toIntervalHour"
        elif unit == "day" or unit == "days":
            name = "toIntervalDay"
        elif unit == "week" or unit == "weeks":
            name = "toIntervalWeek"
        elif unit == "month" or unit == "months":
            name = "toIntervalMonth"
        elif unit == "quarter" or unit == "quarters":
            name = "toIntervalQuarter"
        elif unit == "year" or unit == "years":
            name = "toIntervalYear"
        else:
            raise NotImplementedError(f"Unsupported interval unit: {unit}")

        return ast.Call(name=name, args=[ast.Constant(value=int_count)])

    def visitColumnExprIsNull(self, ctx: HogQLParser.ColumnExprIsNullContext):
        return ast.CompareOperation(
            left=self.visit(ctx.columnExpr()),
            right=ast.Constant(value=None),
            op=ast.CompareOperationOp.NotEq if ctx.NOT() else ast.CompareOperationOp.Eq,
        )

    def visitColumnExprTrim(self, ctx: HogQLParser.ColumnExprTrimContext):
        args = [self.visit(ctx.columnExpr()), self.visit(ctx.string())]
        if ctx.LEADING():
            return ast.Call(name="trimLeft", args=args)
        if ctx.TRAILING():
            return ast.Call(name="trimRight", args=args)
        if ctx.BOTH():
            return ast.Call(name="trim", args=args)
        raise NotImplementedError(f"Unsupported modifier for ColumnExprTrim, must be LEADING, TRAILING or BOTH")

    def visitColumnExprTuple(self, ctx: HogQLParser.ColumnExprTupleContext):
        return ast.Tuple(exprs=self.visit(ctx.columnExprList()) if ctx.columnExprList() else [])

    def visitColumnExprArrayAccess(self, ctx: HogQLParser.ColumnExprArrayAccessContext):
        object: ast.Expr = self.visit(ctx.columnExpr(0))
        property: ast.Expr = self.visit(ctx.columnExpr(1))
        return ast.ArrayAccess(array=object, property=property)

    def visitColumnExprNullArrayAccess(self, ctx: HogQLParser.ColumnExprNullArrayAccessContext):
        object: ast.Expr = self.visit(ctx.columnExpr(0))
        property: ast.Expr = self.visit(ctx.columnExpr(1))
        return ast.ArrayAccess(array=object, property=property, nullish=True)

    def visitColumnExprPropertyAccess(self, ctx: HogQLParser.ColumnExprPropertyAccessContext):
        object = self.visit(ctx.columnExpr())
        property = ast.Constant(value=self.visit(ctx.identifier()))
        return ast.ArrayAccess(array=object, property=property)

    def visitColumnExprNullPropertyAccess(self, ctx: HogQLParser.ColumnExprNullPropertyAccessContext):
        object = self.visit(ctx.columnExpr())
        property = ast.Constant(value=self.visit(ctx.identifier()))
        return ast.ArrayAccess(array=object, property=property, nullish=True)

    def visitColumnExprBetween(self, ctx: HogQLParser.ColumnExprBetweenContext):
        raise NotImplementedError(f"Unsupported node: ColumnExprBetween")

    def visitColumnExprParens(self, ctx: HogQLParser.ColumnExprParensContext):
        return self.visit(ctx.columnExpr())

    def visitColumnExprTimestamp(self, ctx: HogQLParser.ColumnExprTimestampContext):
        raise NotImplementedError(f"Unsupported node: ColumnExprTimestamp")

    def visitColumnExprAnd(self, ctx: HogQLParser.ColumnExprAndContext):
        left = self.visit(ctx.columnExpr(0))
        if isinstance(left, ast.And):
            left_array = left.exprs
        else:
            left_array = [left]

        right = self.visit(ctx.columnExpr(1))
        if isinstance(right, ast.And):
            right_array = right.exprs
        else:
            right_array = [right]

        return ast.And(exprs=left_array + right_array)

    def visitColumnExprOr(self, ctx: HogQLParser.ColumnExprOrContext):
        left = self.visit(ctx.columnExpr(0))
        if isinstance(left, ast.Or):
            left_array = left.exprs
        else:
            left_array = [left]

        right = self.visit(ctx.columnExpr(1))
        if isinstance(right, ast.Or):
            right_array = right.exprs
        else:
            right_array = [right]

        return ast.Or(exprs=left_array + right_array)

    def visitColumnExprTupleAccess(self, ctx: HogQLParser.ColumnExprTupleAccessContext):
        tuple = self.visit(ctx.columnExpr())
        index = int(ctx.DECIMAL_LITERAL().getText())
        return ast.TupleAccess(tuple=tuple, index=index)

    def visitColumnExprNullTupleAccess(self, ctx: HogQLParser.ColumnExprNullTupleAccessContext):
        tuple = self.visit(ctx.columnExpr())
        index = int(ctx.DECIMAL_LITERAL().getText())
        return ast.TupleAccess(tuple=tuple, index=index, nullish=True)

    def visitColumnExprCase(self, ctx: HogQLParser.ColumnExprCaseContext):
        columns = [self.visit(column) for column in ctx.columnExpr()]
        if ctx.caseExpr:
            args = [columns[0], ast.Array(exprs=[]), ast.Array(exprs=[]), columns[-1]]
            for index, column in enumerate(columns):
                if 0 < index < len(columns) - 1:
                    args[((index - 1) % 2) + 1].exprs.append(column)
            return ast.Call(name="transform", args=args)
        elif len(columns) == 3:
            return ast.Call(name="if", args=columns)
        else:
            return ast.Call(name="multiIf", args=columns)

    def visitColumnExprDate(self, ctx: HogQLParser.ColumnExprDateContext):
        raise NotImplementedError(f"Unsupported node: ColumnExprDate")

    def visitColumnExprNot(self, ctx: HogQLParser.ColumnExprNotContext):
        return ast.Not(expr=self.visit(ctx.columnExpr()))

    def visitColumnExprWinFunctionTarget(self, ctx: HogQLParser.ColumnExprWinFunctionTargetContext):
        return ast.WindowFunction(
            name=self.visit(ctx.identifier(0)),
            exprs=self.visit(ctx.columnExprs) if ctx.columnExprs else [],
            args=self.visit(ctx.columnArgList) if ctx.columnArgList else [],
            over_identifier=self.visit(ctx.identifier(1)),
        )

    def visitColumnExprWinFunction(self, ctx: HogQLParser.ColumnExprWinFunctionContext):
        return ast.WindowFunction(
            name=self.visit(ctx.identifier()),
            exprs=self.visit(ctx.columnExprs) if ctx.columnExprs else [],
            args=self.visit(ctx.columnArgList) if ctx.columnArgList else [],
            over_expr=self.visit(ctx.windowExpr()) if ctx.windowExpr() else None,
        )

    def visitColumnExprIdentifier(self, ctx: HogQLParser.ColumnExprIdentifierContext):
        return self.visit(ctx.columnIdentifier())

    def visitColumnExprFunction(self, ctx: HogQLParser.ColumnExprFunctionContext):
        name = self.visit(ctx.identifier())

        parameters: list[ast.Expr] | None = self.visit(ctx.columnExprs) if ctx.columnExprs is not None else None
        # two sets of parameters fn()(), return an empty list for the first even if no parameters
        if ctx.LPAREN(1) and parameters is None:
            parameters = []

        args: list[ast.Expr] = self.visit(ctx.columnArgList) if ctx.columnArgList is not None else []
        distinct = True if ctx.DISTINCT() else False
        return ast.Call(name=name, params=parameters, args=args, distinct=distinct)

    def visitColumnExprAsterisk(self, ctx: HogQLParser.ColumnExprAsteriskContext):
        if ctx.tableIdentifier():
            table = self.visit(ctx.tableIdentifier())
            return ast.Field(chain=[*table, "*"])
        return ast.Field(chain=["*"])

    def visitColumnExprTagElement(self, ctx: HogQLParser.ColumnExprTagElementContext):
        return self.visit(ctx.hogqlxTagElement())

    def visitColumnLambdaExpr(self, ctx: HogQLParser.ColumnLambdaExprContext):
        return ast.Lambda(
            args=[self.visit(identifier) for identifier in ctx.identifier()],
            expr=self.visit(ctx.columnExpr() or ctx.block()),
        )

    def visitWithExprList(self, ctx: HogQLParser.WithExprListContext):
        ctes: dict[str, ast.CTE] = {}
        for expr in ctx.withExpr():
            cte = self.visit(expr)
            ctes[cte.name] = cte
        return ctes

    def visitWithExprSubquery(self, ctx: HogQLParser.WithExprSubqueryContext):
        subquery = self.visit(ctx.selectSetStmt())
        name = self.visit(ctx.identifier())
        return ast.CTE(name=name, expr=subquery, cte_type="subquery")

    def visitWithExprColumn(self, ctx: HogQLParser.WithExprColumnContext):
        expr = self.visit(ctx.columnExpr())
        name = self.visit(ctx.identifier())
        return ast.CTE(name=name, expr=expr, cte_type="column")

    def visitColumnIdentifier(self, ctx: HogQLParser.ColumnIdentifierContext):
        if ctx.placeholder():
            return self.visit(ctx.placeholder())

        table = self.visit(ctx.tableIdentifier()) if ctx.tableIdentifier() else []
        nested = self.visit(ctx.nestedIdentifier()) if ctx.nestedIdentifier() else []

        if len(table) == 0 and len(nested) > 0:
            text = ctx.getText().lower()
            if text == "true":
                return ast.Constant(value=True)
            if text == "false":
                return ast.Constant(value=False)
            return ast.Field(chain=nested)

        return ast.Field(chain=table + nested)

    def visitNestedIdentifier(self, ctx: HogQLParser.NestedIdentifierContext):
        return [self.visit(identifier) for identifier in ctx.identifier()]

    def visitTableExprIdentifier(self, ctx: HogQLParser.TableExprIdentifierContext):
        chain = self.visit(ctx.tableIdentifier())
        return ast.Field(chain=chain)

    def visitTableExprSubquery(self, ctx: HogQLParser.TableExprSubqueryContext):
        return self.visit(ctx.selectSetStmt())

    def visitTableExprPlaceholder(self, ctx: HogQLParser.TableExprPlaceholderContext):
        return self.visit(ctx.placeholder())

    def visitTableExprAlias(self, ctx: HogQLParser.TableExprAliasContext):
        alias: str = self.visit(ctx.alias() or ctx.identifier())
        if alias.lower() in RESERVED_KEYWORDS:
            raise SyntaxError(f'"{alias}" cannot be an alias or identifier, as it\'s a reserved keyword')
        table = self.visit(ctx.tableExpr())
        if isinstance(table, ast.JoinExpr):
            table.alias = alias
            return table
        return ast.JoinExpr(table=table, alias=alias)

    def visitTableExprFunction(self, ctx: HogQLParser.TableExprFunctionContext):
        return self.visit(ctx.tableFunctionExpr())

    def visitTableExprTag(self, ctx: HogQLParser.TableExprTagContext):
        return self.visit(ctx.hogqlxTagElement())

    def visitTableFunctionExpr(self, ctx: HogQLParser.TableFunctionExprContext):
        name = self.visit(ctx.identifier())
        args = self.visit(ctx.tableArgList()) if ctx.tableArgList() else []
        return ast.JoinExpr(table=ast.Field(chain=[name]), table_args=args)

    def visitTableIdentifier(self, ctx: HogQLParser.TableIdentifierContext):
        nested = self.visit(ctx.nestedIdentifier()) if ctx.nestedIdentifier() else []

        if ctx.databaseIdentifier():
            return [self.visit(ctx.databaseIdentifier()), *nested]

        return nested

    def visitTableArgList(self, ctx: HogQLParser.TableArgListContext):
        return [self.visit(arg) for arg in ctx.columnExpr()]

    def visitDatabaseIdentifier(self, ctx: HogQLParser.DatabaseIdentifierContext):
        return self.visit(ctx.identifier())

    def visitFloatingLiteral(self, ctx: HogQLParser.FloatingLiteralContext):
        raise NotImplementedError(f"Unsupported node: visitFloatingLiteral")

    def visitNumberLiteral(self, ctx: HogQLParser.NumberLiteralContext):
        text = ctx.getText().lower()
        if "." in text or "e" in text or text == "-inf" or text == "inf" or text == "nan":
            return ast.Constant(value=float(text))
        return ast.Constant(value=int(text))

    def visitLiteral(self, ctx: HogQLParser.LiteralContext):
        if ctx.NULL_SQL():
            return ast.Constant(value=None)
        if ctx.STRING_LITERAL():
            text = parse_string_literal_ctx(ctx)
            return ast.Constant(value=text)
        return self.visitChildren(ctx)

    def visitInterval(self, ctx: HogQLParser.IntervalContext):
        raise NotImplementedError(f"Unsupported node: Interval")

    def visitKeyword(self, ctx: HogQLParser.KeywordContext):
        raise NotImplementedError(f"Unsupported node: Keyword")

    def visitKeywordForAlias(self, ctx: HogQLParser.KeywordForAliasContext):
        raise NotImplementedError(f"Unsupported node: KeywordForAlias")

    def visitAlias(self, ctx: HogQLParser.AliasContext):
        text = ctx.getText()
        if len(text) >= 2 and (
            (text.startswith("`") and text.endswith("`")) or (text.startswith('"') and text.endswith('"'))
        ):
            text = parse_string_literal_text(text)
        return text

    def visitIdentifier(self, ctx: HogQLParser.IdentifierContext):
        text = ctx.getText()
        if len(text) >= 2 and (
            (text.startswith("`") and text.endswith("`")) or (text.startswith('"') and text.endswith('"'))
        ):
            text = parse_string_literal_text(text)
        return text

    def visitEnumValue(self, ctx: HogQLParser.EnumValueContext):
        raise NotImplementedError(f"Unsupported node: EnumValue")

    def visitColumnExprNullish(self, ctx: HogQLParser.ColumnExprNullishContext):
        return ast.Call(
            name="ifNull",
            args=[self.visit(ctx.columnExpr(0)), self.visit(ctx.columnExpr(1))],
        )

    def visitColumnExprCall(self, ctx: HogQLParser.ColumnExprCallContext):
        return ast.ExprCall(
            expr=self.visit(ctx.columnExpr()), args=self.visit(ctx.columnExprList()) if ctx.columnExprList() else []
        )

    def visitColumnExprCallSelect(self, ctx: HogQLParser.ColumnExprCallSelectContext):
        expr = self.visit(ctx.columnExpr())
        if isinstance(expr, ast.Field) and len(expr.chain) == 1:
            return ast.Call(name=str(expr.chain[0]), args=[self.visit(ctx.selectSetStmt())])
        return ast.ExprCall(expr=expr, args=[self.visit(ctx.selectSetStmt())])

    def visitHogqlxChildElement(self, ctx: HogQLParser.HogqlxChildElementContext):
        if ctx.hogqlxTagElement():
            return self.visit(ctx.hogqlxTagElement())
        if ctx.hogqlxText():
            return self.visit(ctx.hogqlxText())
        return self.visit(ctx.columnExpr())

    def visitHogqlxText(self, ctx: HogQLParser.HogqlxTextContext):
        return ast.Constant(value=ctx.HOGQLX_TEXT_TEXT().getText())

    def visitHogqlxTagElementClosed(self, ctx: HogQLParser.HogqlxTagElementClosedContext):
        kind = self.visit(ctx.identifier())
        attributes = [self.visit(a) for a in ctx.hogqlxTagAttribute()] if ctx.hogqlxTagAttribute() else []
        return ast.HogQLXTag(kind=kind, attributes=attributes)

    def visitHogqlxTagElementNested(self, ctx: HogQLParser.HogqlxTagElementNestedContext):
        opening = self.visit(ctx.identifier(0))
        closing = self.visit(ctx.identifier(1))
        if opening != closing:
            raise SyntaxError(f"Opening and closing HogQLX tags must match. Got {opening} and {closing}")

        attributes = [self.visit(a) for a in ctx.hogqlxTagAttribute()] if ctx.hogqlxTagAttribute() else []

        # ── collect child nodes, discarding pure-indentation whitespace ──
        kept_children = []
        for element in ctx.hogqlxChildElement():
            child = self.visit(element)

            if isinstance(child, ast.Constant) and isinstance(child.value, str):
                v = child.value
                only_ws = v.isspace()
                has_nl = "\n" in v or "\r" in v
                if only_ws and has_nl:
                    continue  # drop indentation text node

            kept_children.append(child)

        if kept_children:
            if any(a.name == "children" for a in attributes):
                raise SyntaxError("Can't have a HogQLX tag with both children and a 'children' attribute")
            attributes.append(ast.HogQLXAttribute(name="children", value=kept_children))

        return ast.HogQLXTag(kind=opening, attributes=attributes)

    def visitHogqlxTagAttribute(self, ctx: HogQLParser.HogqlxTagAttributeContext):
        name = self.visit(ctx.identifier())
        if ctx.columnExpr():
            return ast.HogQLXAttribute(name=name, value=self.visit(ctx.columnExpr()))
        elif ctx.string():
            return ast.HogQLXAttribute(name=name, value=self.visit(ctx.string()))
        else:
            return ast.HogQLXAttribute(name=name, value=ast.Constant(value=True))

    def visitPlaceholder(self, ctx: HogQLParser.PlaceholderContext):
        return ast.Placeholder(expr=self.visit(ctx.columnExpr()))

    def visitColumnExprTemplateString(self, ctx: HogQLParser.ColumnExprTemplateStringContext):
        return self.visit(ctx.templateString())

    def visitString(self, ctx: HogQLParser.StringContext):
        if ctx.STRING_LITERAL():
            return ast.Constant(value=parse_string_literal_ctx(ctx.STRING_LITERAL()))
        return self.visit(ctx.templateString())

    def visitTemplateString(self, ctx: HogQLParser.TemplateStringContext):
        pieces = []
        for chunk in ctx.stringContents():
            pieces.append(self.visit(chunk))

        if len(pieces) == 0:
            return ast.Constant(value="")
        elif len(pieces) == 1:
            return pieces[0]

        return ast.Call(name="concat", args=pieces)

    def visitFullTemplateString(self, ctx: HogQLParser.FullTemplateStringContext):
        pieces = []
        for chunk in ctx.stringContentsFull():
            pieces.append(self.visit(chunk))

        if len(pieces) == 0:
            return ast.Constant(value="")
        elif len(pieces) == 1:
            return pieces[0]

        return ast.Call(name="concat", args=pieces)

    def visitStringContents(self, ctx: HogQLParser.StringContentsContext):
        if ctx.STRING_TEXT():
            return ast.Constant(value=parse_string_text_ctx(ctx.STRING_TEXT(), escape_quotes=True))
        elif ctx.columnExpr():
            return self.visit(ctx.columnExpr())
        return ast.Constant(value="")

    def visitStringContentsFull(self, ctx: HogQLParser.StringContentsFullContext):
        if ctx.FULL_STRING_TEXT():
            return ast.Constant(value=parse_string_text_ctx(ctx.FULL_STRING_TEXT(), escape_quotes=False))
        elif ctx.columnExpr():
            return self.visit(ctx.columnExpr())
        return ast.Constant(value="")
