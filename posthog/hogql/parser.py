from typing import Dict, List, Literal, Optional, cast

from antlr4 import CommonTokenStream, InputStream, ParseTreeVisitor, ParserRuleContext
from antlr4.error.ErrorListener import ErrorListener

from posthog.hogql import ast
from posthog.hogql.constants import RESERVED_KEYWORDS
from posthog.hogql.errors import NotImplementedException, HogQLException, SyntaxException
from posthog.hogql.grammar.HogQLLexer import HogQLLexer
from posthog.hogql.grammar.HogQLParser import HogQLParser
from posthog.hogql.parse_string import parse_string, parse_string_literal
from posthog.hogql.placeholders import replace_placeholders


def parse_expr(expr: str, placeholders: Optional[Dict[str, ast.Expr]] = None) -> ast.Expr:
    parse_tree = get_parser(expr).expr()
    node = HogQLParseTreeConverter().visit(parse_tree)
    if placeholders:
        return replace_placeholders(node, placeholders)
    return node


def parse_order_expr(order_expr: str, placeholders: Optional[Dict[str, ast.Expr]] = None) -> ast.Expr:
    parse_tree = get_parser(order_expr).orderExpr()
    node = HogQLParseTreeConverter().visit(parse_tree)
    if placeholders:
        return replace_placeholders(node, placeholders)
    return node


def parse_select(
    statement: str, placeholders: Optional[Dict[str, ast.Expr]] = None
) -> ast.SelectQuery | ast.SelectUnionQuery:
    parse_tree = get_parser(statement).select()
    node = HogQLParseTreeConverter().visit(parse_tree)
    if placeholders:
        node = replace_placeholders(node, placeholders)
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
        raise SyntaxException(msg, start=start, end=len(self.query))


class HogQLParseTreeConverter(ParseTreeVisitor):
    def visit(self, ctx: ParserRuleContext):
        start = ctx.start.start if ctx.start else None
        end = ctx.stop.stop + 1 if ctx.stop else None
        try:
            node = super().visit(ctx)
            if isinstance(node, ast.AST):
                node.start = start
                node.end = end
            return node
        except HogQLException as e:
            if start is not None and end is not None and e.start is None or e.end is None:
                e.start = start
                e.end = end
            raise e

    def visitSelect(self, ctx: HogQLParser.SelectContext):
        return self.visit(ctx.selectUnionStmt() or ctx.selectStmt())

    def visitSelectUnionStmt(self, ctx: HogQLParser.SelectUnionStmtContext):
        select_queries: List[ast.SelectQuery | ast.SelectUnionQuery] = [
            self.visit(select) for select in ctx.selectStmtWithParens()
        ]
        flattened_queries: List[ast.SelectQuery] = []
        for query in select_queries:
            if isinstance(query, ast.SelectQuery):
                flattened_queries.append(query)
            elif isinstance(query, ast.SelectUnionQuery):
                flattened_queries.extend(query.select_queries)
            else:
                raise Exception(f"Unexpected query node type {type(query).__name__}")
        if len(flattened_queries) == 1:
            return flattened_queries[0]
        return ast.SelectUnionQuery(select_queries=flattened_queries)

    def visitSelectStmtWithParens(self, ctx: HogQLParser.SelectStmtWithParensContext):
        return self.visit(ctx.selectStmt() or ctx.selectUnionStmt())

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
        )

        if ctx.windowClause():
            select_query.window_exprs = {}
            for index, window_expr in enumerate(ctx.windowClause().windowExpr()):
                name = self.visit(ctx.windowClause().identifier()[index])
                select_query.window_exprs[name] = self.visit(window_expr)

        if ctx.limitClause():
            limit_clause = ctx.limitClause()
            limit_expr = limit_clause.limitExpr()
            if limit_expr.columnExpr(0):
                select_query.limit = self.visit(limit_expr.columnExpr(0))
            if limit_expr.columnExpr(1):
                select_query.offset = self.visit(limit_expr.columnExpr(1))
            if limit_clause.columnExprList():
                select_query.limit_by = self.visit(limit_clause.columnExprList())
            if limit_clause.WITH() and limit_clause.TIES():
                select_query.limit_with_ties = True

        if ctx.topClause():
            raise NotImplementedException(f"Unsupported: SelectStmt.topClause()")
        if ctx.arrayJoinClause():
            raise NotImplementedException(f"Unsupported: SelectStmt.arrayJoinClause()")
        if ctx.settingsClause():
            raise NotImplementedException(f"Unsupported: SelectStmt.settingsClause()")

        return select_query

    def visitWithClause(self, ctx: HogQLParser.WithClauseContext):
        return self.visit(ctx.withExprList())

    def visitTopClause(self, ctx: HogQLParser.TopClauseContext):
        raise NotImplementedException(f"Unsupported node: TopClause")

    def visitFromClause(self, ctx: HogQLParser.FromClauseContext):
        return self.visit(ctx.joinExpr())

    def visitArrayJoinClause(self, ctx: HogQLParser.ArrayJoinClauseContext):
        raise NotImplementedException(f"Unsupported node: ArrayJoinClause")

    def visitWindowClause(self, ctx: HogQLParser.WindowClauseContext):
        raise NotImplementedException(f"Unsupported node: WindowClause")

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

    def visitProjectionOrderByClause(self, ctx: HogQLParser.ProjectionOrderByClauseContext):
        raise NotImplementedException(f"Unsupported node: ProjectionOrderByClause")

    def visitLimitClause(self, ctx: HogQLParser.LimitClauseContext):
        raise Exception(f"Parsed as part of SelectStmt, can't parse directly.")

    def visitSettingsClause(self, ctx: HogQLParser.SettingsClauseContext):
        raise NotImplementedException(f"Unsupported node: SettingsClause")

    def visitJoinExprOp(self, ctx: HogQLParser.JoinExprOpContext):
        if ctx.GLOBAL():
            raise NotImplementedException(f"Unsupported: GLOBAL JOIN")
        if ctx.LOCAL():
            raise NotImplementedException(f"Unsupported: LOCAL JOIN")

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
            table.table_final = table_final
            table.sample = sample
            return table
        return ast.JoinExpr(table=table, table_final=table_final, sample=sample)

    def visitJoinExprParens(self, ctx: HogQLParser.JoinExprParensContext):
        return self.visit(ctx.joinExpr())

    def visitJoinExprCrossOp(self, ctx: HogQLParser.JoinExprCrossOpContext):
        raise NotImplementedException(f"Unsupported node: JoinExprCrossOp")

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
        if ctx.LEFT():
            tokens.append("FULL")
        if ctx.OUTER():
            tokens.append("OUTER")
        if ctx.ALL():
            tokens.append("ALL")
        if ctx.ANY():
            tokens.append("ANY")
        return " ".join(tokens)

    def visitJoinOpCross(self, ctx: HogQLParser.JoinOpCrossContext):
        raise NotImplementedException(f"Unsupported node: JoinOpCross")

    def visitJoinConstraintClause(self, ctx: HogQLParser.JoinConstraintClauseContext):
        if ctx.USING():
            raise NotImplementedException(f"Unsupported: JOIN ... USING")
        column_expr_list = self.visit(ctx.columnExprList())
        if len(column_expr_list) != 1:
            raise NotImplementedException(f"Unsupported: JOIN ... ON with multiple expressions")
        return column_expr_list[0]

    def visitSampleClause(self, ctx: HogQLParser.SampleClauseContext):
        ratio_expressions = ctx.ratioExpr()

        sample_ratio_expr = self.visit(ratio_expressions[0])
        offset_ratio_expr = self.visit(ratio_expressions[1]) if len(ratio_expressions) > 1 and ctx.OFFSET() else None

        return ast.SampleExpr(sample_value=sample_ratio_expr, offset_value=offset_ratio_expr)

    def visitLimitExpr(self, ctx: HogQLParser.LimitExprContext):
        raise NotImplementedException(f"Unsupported node: LimitExpr")

    def visitOrderExprList(self, ctx: HogQLParser.OrderExprListContext):
        return [self.visit(expr) for expr in ctx.orderExpr()]

    def visitOrderExpr(self, ctx: HogQLParser.OrderExprContext):
        order = "DESC" if ctx.DESC() or ctx.DESCENDING() else "ASC"
        return ast.OrderExpr(expr=self.visit(ctx.columnExpr()), order=cast(Literal["ASC", "DESC"], order))

    def visitRatioExpr(self, ctx: HogQLParser.RatioExprContext):
        number_literals = ctx.numberLiteral()

        left = number_literals[0]
        right = number_literals[1] if ctx.SLASH() and len(number_literals) > 1 else None

        return ast.RatioExpr(
            left=self.visitNumberLiteral(left), right=self.visitNumberLiteral(right) if right else None
        )

    def visitSettingExprList(self, ctx: HogQLParser.SettingExprListContext):
        raise NotImplementedException(f"Unsupported node: SettingExprList")

    def visitSettingExpr(self, ctx: HogQLParser.SettingExprContext):
        raise NotImplementedException(f"Unsupported node: SettingExpr")

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
        raise NotImplementedException(f"Unsupported node: ColumnTypeExprSimple")

    def visitColumnTypeExprNested(self, ctx: HogQLParser.ColumnTypeExprNestedContext):
        raise NotImplementedException(f"Unsupported node: ColumnTypeExprNested")

    def visitColumnTypeExprEnum(self, ctx: HogQLParser.ColumnTypeExprEnumContext):
        raise NotImplementedException(f"Unsupported node: ColumnTypeExprEnum")

    def visitColumnTypeExprComplex(self, ctx: HogQLParser.ColumnTypeExprComplexContext):
        raise NotImplementedException(f"Unsupported node: ColumnTypeExprComplex")

    def visitColumnTypeExprParam(self, ctx: HogQLParser.ColumnTypeExprParamContext):
        raise NotImplementedException(f"Unsupported node: ColumnTypeExprParam")

    def visitColumnExprList(self, ctx: HogQLParser.ColumnExprListContext):
        return [self.visit(c) for c in ctx.columnsExpr()]

    def visitColumnsExprAsterisk(self, ctx: HogQLParser.ColumnsExprAsteriskContext):
        if ctx.tableIdentifier():
            table = self.visit(ctx.tableIdentifier())
            return ast.Field(chain=table + ["*"])
        return ast.Field(chain=["*"])

    def visitColumnsExprSubquery(self, ctx: HogQLParser.ColumnsExprSubqueryContext):
        return self.visit(ctx.selectUnionStmt())

    def visitColumnsExprColumn(self, ctx: HogQLParser.ColumnsExprColumnContext):
        return self.visit(ctx.columnExpr())

    def visitColumnExprTernaryOp(self, ctx: HogQLParser.ColumnExprTernaryOpContext):
        return ast.Call(
            name="if",
            args=[self.visit(ctx.columnExpr(0)), self.visit(ctx.columnExpr(1)), self.visit(ctx.columnExpr(2))],
        )

    def visitColumnExprAlias(self, ctx: HogQLParser.ColumnExprAliasContext):
        if ctx.alias():
            alias = self.visit(ctx.alias())
        elif ctx.identifier():
            alias = self.visit(ctx.identifier())
        elif ctx.STRING_LITERAL():
            alias = parse_string_literal(ctx.STRING_LITERAL())
        else:
            raise NotImplementedException(f"Must specify an alias.")
        expr = self.visit(ctx.columnExpr())

        if alias in RESERVED_KEYWORDS:
            raise HogQLException(f"Alias '{alias}' is a reserved keyword.")

        return ast.Alias(expr=expr, alias=alias)

    def visitColumnExprExtract(self, ctx: HogQLParser.ColumnExprExtractContext):
        raise NotImplementedException(f"Unsupported node: ColumnExprExtract")

    def visitColumnExprNegate(self, ctx: HogQLParser.ColumnExprNegateContext):
        return ast.BinaryOperation(
            op=ast.BinaryOperationOp.Sub, left=ast.Constant(value=0), right=self.visit(ctx.columnExpr())
        )

    def visitColumnExprSubquery(self, ctx: HogQLParser.ColumnExprSubqueryContext):
        return self.visit(ctx.selectUnionStmt())

    def visitColumnExprLiteral(self, ctx: HogQLParser.ColumnExprLiteralContext):
        return self.visitChildren(ctx)

    def visitColumnExprArray(self, ctx: HogQLParser.ColumnExprArrayContext):
        return ast.Array(exprs=self.visit(ctx.columnExprList()) if ctx.columnExprList() else [])

    def visitColumnExprSubstring(self, ctx: HogQLParser.ColumnExprSubstringContext):
        raise NotImplementedException(f"Unsupported node: ColumnExprSubstring")

    def visitColumnExprCast(self, ctx: HogQLParser.ColumnExprCastContext):
        raise NotImplementedException(f"Unsupported node: ColumnExprCast")

    def visitColumnExprPrecedence1(self, ctx: HogQLParser.ColumnExprPrecedence1Context):
        if ctx.SLASH():
            op = ast.BinaryOperationOp.Div
        elif ctx.ASTERISK():
            op = ast.BinaryOperationOp.Mult
        elif ctx.PERCENT():
            op = ast.BinaryOperationOp.Mod
        else:
            raise NotImplementedException(f"Unsupported ColumnExprPrecedence1: {ctx.operator.text}")
        left = self.visit(ctx.left)
        right = self.visit(ctx.right)
        return ast.BinaryOperation(left=left, right=right, op=op)

    def visitColumnExprPrecedence2(self, ctx: HogQLParser.ColumnExprPrecedence2Context):
        left = self.visit(ctx.left)
        right = self.visit(ctx.right)

        if ctx.PLUS():
            return ast.BinaryOperation(left=left, right=right, op=ast.BinaryOperationOp.Add)
        elif ctx.DASH():
            return ast.BinaryOperation(left=left, right=right, op=ast.BinaryOperationOp.Sub)
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
            raise NotImplementedException(f"Unsupported ColumnExprPrecedence2: {ctx.operator.text}")

    def visitColumnExprPrecedence3(self, ctx: HogQLParser.ColumnExprPrecedence3Context):
        if ctx.EQ_SINGLE() or ctx.EQ_DOUBLE():
            op = ast.CompareOperationOp.Eq
        elif ctx.NOT_EQ():
            op = ast.CompareOperationOp.NotEq
        elif ctx.LT():
            op = ast.CompareOperationOp.Lt
        elif ctx.LE():
            op = ast.CompareOperationOp.LtE
        elif ctx.GT():
            op = ast.CompareOperationOp.Gt
        elif ctx.GE():
            op = ast.CompareOperationOp.GtE
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
        elif ctx.IN():
            if ctx.GLOBAL():
                raise NotImplementedException(f"Unsupported node: IN GLOBAL")
            if ctx.NOT():
                op = ast.CompareOperationOp.NotIn
            else:
                op = ast.CompareOperationOp.In
        else:
            raise NotImplementedException(f"Unsupported ColumnExprPrecedence3: {ctx.getText()}")
        return ast.CompareOperation(left=self.visit(ctx.left), right=self.visit(ctx.right), op=op)

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
            raise NotImplementedException(f"Unsupported interval type: {ctx.interval().getText()}")

        return ast.Call(name=name, args=[self.visit(ctx.columnExpr())])

    def visitColumnExprIsNull(self, ctx: HogQLParser.ColumnExprIsNullContext):
        return ast.CompareOperation(
            left=self.visit(ctx.columnExpr()),
            right=ast.Constant(value=None),
            op=ast.CompareOperationOp.NotEq if ctx.NOT() else ast.CompareOperationOp.Eq,
        )

    def visitColumnExprTrim(self, ctx: HogQLParser.ColumnExprTrimContext):
        raise NotImplementedException(f"Unsupported node: ColumnExprTrim")

    def visitColumnExprTuple(self, ctx: HogQLParser.ColumnExprTupleContext):
        return ast.Tuple(exprs=self.visit(ctx.columnExprList()) if ctx.columnExprList() else [])

    def visitColumnExprArrayAccess(self, ctx: HogQLParser.ColumnExprArrayAccessContext):
        object = self.visit(ctx.columnExpr(0))
        property = self.visit(ctx.columnExpr(1))
        if isinstance(object, ast.Field) and isinstance(property, ast.Constant):
            return ast.Field(chain=object.chain + [property.value])
        else:
            return ast.ArrayAccess(array=object, property=property)

    def visitColumnExprBetween(self, ctx: HogQLParser.ColumnExprBetweenContext):
        raise NotImplementedException(f"Unsupported node: ColumnExprBetween")

    def visitColumnExprParens(self, ctx: HogQLParser.ColumnExprParensContext):
        return self.visit(ctx.columnExpr())

    def visitColumnExprTimestamp(self, ctx: HogQLParser.ColumnExprTimestampContext):
        raise NotImplementedException(f"Unsupported node: ColumnExprTimestamp")

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
        return ast.TupleAccess(tuple=self.visit(ctx.columnExpr()), index=int(ctx.DECIMAL_LITERAL().getText()))

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
        raise NotImplementedException(f"Unsupported node: ColumnExprDate")

    def visitColumnExprNot(self, ctx: HogQLParser.ColumnExprNotContext):
        return ast.Not(expr=self.visit(ctx.columnExpr()))

    def visitColumnExprWinFunctionTarget(self, ctx: HogQLParser.ColumnExprWinFunctionTargetContext):
        return ast.WindowFunction(
            name=self.visit(ctx.identifier(0)),
            args=self.visit(ctx.columnExprList()) if ctx.columnExprList() else [],
            over_identifier=self.visit(ctx.identifier(1)),
        )

    def visitColumnExprWinFunction(self, ctx: HogQLParser.ColumnExprWinFunctionContext):
        return ast.WindowFunction(
            name=self.visit(ctx.identifier()),
            args=self.visit(ctx.columnExprList()) if ctx.columnExprList() else [],
            over_expr=self.visit(ctx.windowExpr()) if ctx.windowExpr() else None,
        )

    def visitColumnExprIdentifier(self, ctx: HogQLParser.ColumnExprIdentifierContext):
        return self.visit(ctx.columnIdentifier())

    def visitColumnExprFunction(self, ctx: HogQLParser.ColumnExprFunctionContext):
        if ctx.columnExprList():
            raise NotImplementedException(f"Functions that return functions are not supported")
        name = self.visit(ctx.identifier())
        args = self.visit(ctx.columnArgList()) if ctx.columnArgList() else []
        distinct = True if ctx.DISTINCT() else None
        return ast.Call(name=name, args=args, distinct=distinct)

    def visitColumnExprAsterisk(self, ctx: HogQLParser.ColumnExprAsteriskContext):
        if ctx.tableIdentifier():
            table = self.visit(ctx.tableIdentifier())
            return ast.Field(chain=table + ["*"])
        return ast.Field(chain=["*"])

    def visitColumnArgList(self, ctx: HogQLParser.ColumnArgListContext):
        return [self.visit(arg) for arg in ctx.columnArgExpr()]

    def visitColumnArgExpr(self, ctx: HogQLParser.ColumnArgExprContext):
        return self.visitChildren(ctx)

    def visitColumnLambdaExpr(self, ctx: HogQLParser.ColumnLambdaExprContext):
        return ast.Lambda(
            args=[self.visit(identifier) for identifier in ctx.identifier()], expr=self.visit(ctx.columnExpr())
        )

    def visitWithExprList(self, ctx: HogQLParser.WithExprListContext):
        ctes: Dict[str, ast.CTE] = {}
        for expr in ctx.withExpr():
            cte = self.visit(expr)
            ctes[cte.name] = cte
        return ctes

    def visitWithExprSubquery(self, ctx: HogQLParser.WithExprSubqueryContext):
        subquery = self.visit(ctx.selectUnionStmt())
        name = self.visit(ctx.identifier())
        return ast.CTE(name=name, expr=subquery, cte_type="subquery")

    def visitWithExprColumn(self, ctx: HogQLParser.WithExprColumnContext):
        expr = self.visit(ctx.columnExpr())
        name = self.visit(ctx.identifier())
        return ast.CTE(name=name, expr=expr, cte_type="column")

    def visitColumnIdentifier(self, ctx: HogQLParser.ColumnIdentifierContext):
        if ctx.PLACEHOLDER():
            return ast.Placeholder(field=parse_string_literal(ctx.PLACEHOLDER()))

        table = self.visit(ctx.tableIdentifier()) if ctx.tableIdentifier() else []
        nested = self.visit(ctx.nestedIdentifier()) if ctx.nestedIdentifier() else []

        if len(table) == 0 and len(nested) > 0:
            if isinstance(nested[0], ast.Expr):
                return nested[0]
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
        return self.visit(ctx.selectUnionStmt())

    def visitTableExprAlias(self, ctx: HogQLParser.TableExprAliasContext):
        alias = self.visit(ctx.alias() or ctx.identifier())
        if alias in RESERVED_KEYWORDS:
            raise HogQLException(f"Alias '{alias}' is a reserved keyword.")
        return ast.JoinExpr(table=self.visit(ctx.tableExpr()), alias=alias)

    def visitTableExprFunction(self, ctx: HogQLParser.TableExprFunctionContext):
        raise NotImplementedException(f"Unsupported node: TableExprFunction")

    def visitTableFunctionExpr(self, ctx: HogQLParser.TableFunctionExprContext):
        raise NotImplementedException(f"Unsupported node: TableFunctionExpr")

    def visitTableIdentifier(self, ctx: HogQLParser.TableIdentifierContext):
        text = self.visit(ctx.identifier())
        if ctx.databaseIdentifier():
            return [self.visit(ctx.databaseIdentifier()), text]
        return [text]

    def visitTableArgList(self, ctx: HogQLParser.TableArgListContext):
        raise NotImplementedException(f"Unsupported node: TableArgList")

    def visitTableArgExpr(self, ctx: HogQLParser.TableArgExprContext):
        raise NotImplementedException(f"Unsupported node: TableArgExpr")

    def visitDatabaseIdentifier(self, ctx: HogQLParser.DatabaseIdentifierContext):
        return self.visit(ctx.identifier())

    def visitFloatingLiteral(self, ctx: HogQLParser.FloatingLiteralContext):
        raise NotImplementedException(f"Unsupported node: visitFloatingLiteral")

    def visitNumberLiteral(self, ctx: HogQLParser.NumberLiteralContext):
        text = ctx.getText().lower()
        if "." in text or "e" in text or text == "-inf" or text == "inf" or text == "nan":
            return ast.Constant(value=float(text))
        return ast.Constant(value=int(text))

    def visitLiteral(self, ctx: HogQLParser.LiteralContext):
        if ctx.NULL_SQL():
            return ast.Constant(value=None)
        if ctx.STRING_LITERAL():
            text = parse_string_literal(ctx)
            return ast.Constant(value=text)
        return self.visitChildren(ctx)

    def visitInterval(self, ctx: HogQLParser.IntervalContext):
        raise NotImplementedException(f"Unsupported node: Interval")

    def visitKeyword(self, ctx: HogQLParser.KeywordContext):
        raise NotImplementedException(f"Unsupported node: Keyword")

    def visitKeywordForAlias(self, ctx: HogQLParser.KeywordForAliasContext):
        raise NotImplementedException(f"Unsupported node: KeywordForAlias")

    def visitAlias(self, ctx: HogQLParser.AliasContext):
        text = ctx.getText()
        if len(text) >= 2 and (
            (text.startswith("`") and text.endswith("`")) or (text.startswith('"') and text.endswith('"'))
        ):
            text = parse_string(text)
        return text

    def visitIdentifier(self, ctx: HogQLParser.IdentifierContext):
        text = ctx.getText()
        if len(text) >= 2 and (
            (text.startswith("`") and text.endswith("`")) or (text.startswith('"') and text.endswith('"'))
        ):
            text = parse_string(text)
        return text

    def visitIdentifierOrNull(self, ctx: HogQLParser.IdentifierOrNullContext):
        raise NotImplementedException(f"Unsupported node: IdentifierOrNull")

    def visitEnumValue(self, ctx: HogQLParser.EnumValueContext):
        raise NotImplementedException(f"Unsupported node: EnumValue")
