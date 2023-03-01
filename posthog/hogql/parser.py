from typing import Dict, Literal, Optional, cast

from antlr4 import CommonTokenStream, InputStream, ParseTreeVisitor
from antlr4.error.ErrorListener import ErrorListener

from posthog.hogql import ast
from posthog.hogql.constants import RESERVED_KEYWORDS
from posthog.hogql.grammar.HogQLLexer import HogQLLexer
from posthog.hogql.grammar.HogQLParser import HogQLParser
from posthog.hogql.parse_string import parse_string, parse_string_literal
from posthog.hogql.placeholders import assert_no_placeholders, replace_placeholders


def parse_expr(expr: str, placeholders: Optional[Dict[str, ast.Expr]] = None, no_placeholders=False) -> ast.Expr:
    parse_tree = get_parser(expr).expr()
    node = HogQLParseTreeConverter().visit(parse_tree)
    if placeholders:
        return replace_placeholders(node, placeholders)
    elif no_placeholders:
        assert_no_placeholders(node)

    return node


def parse_order_expr(
    order_expr: str, placeholders: Optional[Dict[str, ast.Expr]] = None, no_placeholders=False
) -> ast.Expr:
    parse_tree = get_parser(order_expr).orderExpr()
    node = HogQLParseTreeConverter().visit(parse_tree)
    if placeholders:
        return replace_placeholders(node, placeholders)
    elif no_placeholders:
        assert_no_placeholders(node)

    return node


def parse_select(
    statement: str, placeholders: Optional[Dict[str, ast.Expr]] = None, no_placeholders=False
) -> ast.SelectQuery:
    parse_tree = get_parser(statement).select()
    node = HogQLParseTreeConverter().visit(parse_tree)
    if placeholders:
        node = replace_placeholders(node, placeholders)
    elif no_placeholders:
        assert_no_placeholders(node)
    return node


def get_parser(query: str) -> HogQLParser:
    input_stream = InputStream(data=query)
    lexer = HogQLLexer(input_stream)
    stream = CommonTokenStream(lexer)
    parser = HogQLParser(stream)
    parser.removeErrorListeners()
    parser.addErrorListener(HogQLErrorListener())
    return parser


class HogQLErrorListener(ErrorListener):
    def syntaxError(self, recognizer, offendingSymbol, line, column, msg, e):
        raise SyntaxError(f"line {line}, column {column}: {msg}")


class HogQLParseTreeConverter(ParseTreeVisitor):
    def visitSelect(self, ctx: HogQLParser.SelectContext):
        return self.visit(ctx.selectUnionStmt() or ctx.selectStmt())

    def visitSelectUnionStmt(self, ctx: HogQLParser.SelectUnionStmtContext):
        selects = ctx.selectStmtWithParens()
        if len(selects) != 1:
            raise NotImplementedError(f"Unsupported: UNION ALL")
        return self.visit(selects[0])

    def visitSelectStmtWithParens(self, ctx: HogQLParser.SelectStmtWithParensContext):
        return self.visit(ctx.selectStmt() or ctx.selectUnionStmt())

    def visitSelectStmt(self, ctx: HogQLParser.SelectStmtContext):
        select_query = ast.SelectQuery(
            select=self.visit(ctx.columnExprList()) if ctx.columnExprList() else [],
            distinct=True if ctx.DISTINCT() else None,
            select_from=self.visit(ctx.fromClause()) if ctx.fromClause() else None,
            where=self.visit(ctx.whereClause()) if ctx.whereClause() else None,
            prewhere=self.visit(ctx.prewhereClause()) if ctx.prewhereClause() else None,
            having=self.visit(ctx.havingClause()) if ctx.havingClause() else None,
            group_by=self.visit(ctx.groupByClause()) if ctx.groupByClause() else None,
            order_by=self.visit(ctx.orderByClause()) if ctx.orderByClause() else None,
        )

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

        if ctx.withClause():
            raise NotImplementedError(f"Unsupported: SelectStmt.withClause()")
        if ctx.topClause():
            raise NotImplementedError(f"Unsupported: SelectStmt.topClause()")
        if ctx.arrayJoinClause():
            raise NotImplementedError(f"Unsupported: SelectStmt.arrayJoinClause()")
        if ctx.windowClause():
            raise NotImplementedError(f"Unsupported: SelectStmt.windowClause()")
        if ctx.settingsClause():
            raise NotImplementedError(f"Unsupported: SelectStmt.settingsClause()")

        return select_query

    def visitWithClause(self, ctx: HogQLParser.WithClauseContext):
        raise NotImplementedError(f"Unsupported node: WithClause")

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

    def visitProjectionOrderByClause(self, ctx: HogQLParser.ProjectionOrderByClauseContext):
        raise NotImplementedError(f"Unsupported node: ProjectionOrderByClause")

    def visitLimitClause(self, ctx: HogQLParser.LimitClauseContext):
        raise Exception(f"Parsed as part of SelectStmt, can't parse directly.")

    def visitSettingsClause(self, ctx: HogQLParser.SettingsClauseContext):
        raise NotImplementedError(f"Unsupported node: SettingsClause")

    def visitJoinExprOp(self, ctx: HogQLParser.JoinExprOpContext):
        if ctx.GLOBAL():
            raise NotImplementedError(f"Unsupported: GLOBAL JOIN")
        if ctx.LOCAL():
            raise NotImplementedError(f"Unsupported: LOCAL JOIN")

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
        if ctx.sampleClause():
            raise NotImplementedError(f"Unsupported: SAMPLE (JoinExprTable.sampleClause)")
        table = self.visit(ctx.tableExpr())
        table_final = True if ctx.FINAL() else None
        if isinstance(table, ast.JoinExpr):
            # visitTableExprAlias returns a JoinExpr to pass the alias
            table.table_final = table_final
            return table
        return ast.JoinExpr(table=table, table_final=table_final)

    def visitJoinExprParens(self, ctx: HogQLParser.JoinExprParensContext):
        return self.visit(ctx.joinExpr())

    def visitJoinExprCrossOp(self, ctx: HogQLParser.JoinExprCrossOpContext):
        raise NotImplementedError(f"Unsupported node: JoinExprCrossOp")

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
        raise NotImplementedError(f"Unsupported node: JoinOpCross")

    def visitJoinConstraintClause(self, ctx: HogQLParser.JoinConstraintClauseContext):
        if ctx.USING():
            raise NotImplementedError(f"Unsupported: JOIN ... USING")
        column_expr_list = self.visit(ctx.columnExprList())
        if len(column_expr_list) != 1:
            raise NotImplementedError(f"Unsupported: JOIN ... ON with multiple expressions")
        return column_expr_list[0]

    def visitSampleClause(self, ctx: HogQLParser.SampleClauseContext):
        raise NotImplementedError(f"Unsupported node: SampleClause")

    def visitLimitExpr(self, ctx: HogQLParser.LimitExprContext):
        raise NotImplementedError(f"Unsupported node: LimitExpr")

    def visitOrderExprList(self, ctx: HogQLParser.OrderExprListContext):
        return [self.visit(expr) for expr in ctx.orderExpr()]

    def visitOrderExpr(self, ctx: HogQLParser.OrderExprContext):
        order = "DESC" if ctx.DESC() or ctx.DESCENDING() else "ASC"
        return ast.OrderExpr(expr=self.visit(ctx.columnExpr()), order=cast(Literal["ASC", "DESC"], order))

    def visitRatioExpr(self, ctx: HogQLParser.RatioExprContext):
        raise NotImplementedError(f"Unsupported node: RatioExpr")

    def visitSettingExprList(self, ctx: HogQLParser.SettingExprListContext):
        raise NotImplementedError(f"Unsupported node: SettingExprList")

    def visitSettingExpr(self, ctx: HogQLParser.SettingExprContext):
        raise NotImplementedError(f"Unsupported node: SettingExpr")

    def visitWindowExpr(self, ctx: HogQLParser.WindowExprContext):
        raise NotImplementedError(f"Unsupported node: WindowExpr")

    def visitWinPartitionByClause(self, ctx: HogQLParser.WinPartitionByClauseContext):
        raise NotImplementedError(f"Unsupported node: WinPartitionByClause")

    def visitWinOrderByClause(self, ctx: HogQLParser.WinOrderByClauseContext):
        raise NotImplementedError(f"Unsupported node: WinOrderByClause")

    def visitWinFrameClause(self, ctx: HogQLParser.WinFrameClauseContext):
        raise NotImplementedError(f"Unsupported node: WinFrameClause")

    def visitFrameStart(self, ctx: HogQLParser.FrameStartContext):
        raise NotImplementedError(f"Unsupported node: FrameStart")

    def visitFrameBetween(self, ctx: HogQLParser.FrameBetweenContext):
        raise NotImplementedError(f"Unsupported node: FrameBetween")

    def visitWinFrameBound(self, ctx: HogQLParser.WinFrameBoundContext):
        raise NotImplementedError(f"Unsupported node: WinFrameBound")

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
        raise NotImplementedError(f"Unsupported node: ColumnExprTernaryOp")

    def visitColumnExprAlias(self, ctx: HogQLParser.ColumnExprAliasContext):
        if ctx.alias():
            alias = self.visit(ctx.alias())
        elif ctx.identifier():
            alias = self.visit(ctx.identifier())
        elif ctx.STRING_LITERAL():
            alias = parse_string_literal(ctx.STRING_LITERAL())
        else:
            raise NotImplementedError(f"Must specify an alias.")
        expr = self.visit(ctx.columnExpr())

        if alias in RESERVED_KEYWORDS:
            raise ValueError(f"Alias '{alias}' is a reserved keyword.")

        return ast.Alias(expr=expr, alias=alias)

    def visitColumnExprExtract(self, ctx: HogQLParser.ColumnExprExtractContext):
        raise NotImplementedError(f"Unsupported node: ColumnExprExtract")

    def visitColumnExprNegate(self, ctx: HogQLParser.ColumnExprNegateContext):
        return ast.BinaryOperation(
            op=ast.BinaryOperationType.Sub, left=ast.Constant(value=0), right=self.visit(ctx.columnExpr())
        )

    def visitColumnExprSubquery(self, ctx: HogQLParser.ColumnExprSubqueryContext):
        return self.visit(ctx.selectUnionStmt())

    def visitColumnExprLiteral(self, ctx: HogQLParser.ColumnExprLiteralContext):
        return self.visitChildren(ctx)

    def visitColumnExprArray(self, ctx: HogQLParser.ColumnExprArrayContext):
        raise NotImplementedError(f"Unsupported node: ColumnExprArray")

    def visitColumnExprSubstring(self, ctx: HogQLParser.ColumnExprSubstringContext):
        raise NotImplementedError(f"Unsupported node: ColumnExprSubstring")

    def visitColumnExprCast(self, ctx: HogQLParser.ColumnExprCastContext):
        raise NotImplementedError(f"Unsupported node: ColumnExprCast")

    def visitColumnExprPrecedence1(self, ctx: HogQLParser.ColumnExprPrecedence1Context):
        if ctx.SLASH():
            op = ast.BinaryOperationType.Div
        elif ctx.ASTERISK():
            op = ast.BinaryOperationType.Mult
        elif ctx.PERCENT():
            op = ast.BinaryOperationType.Mod
        else:
            raise NotImplementedError(f"Unsupported ColumnExprPrecedence1: {ctx.operator.text}")
        left = self.visit(ctx.left)
        right = self.visit(ctx.right)
        return ast.BinaryOperation(left=left, right=right, op=op)

    def visitColumnExprPrecedence2(self, ctx: HogQLParser.ColumnExprPrecedence2Context):
        if ctx.PLUS():
            op = ast.BinaryOperationType.Add
        elif ctx.DASH():
            op = ast.BinaryOperationType.Sub
        elif ctx.CONCAT():
            raise NotImplementedError(f"Yet unsupported text concat operation: {ctx.operator.text}")
        else:
            raise NotImplementedError(f"Unsupported ColumnExprPrecedence2: {ctx.operator.text}")
        left = self.visit(ctx.left)
        right = self.visit(ctx.right)
        return ast.BinaryOperation(left=left, right=right, op=op)

    def visitColumnExprPrecedence3(self, ctx: HogQLParser.ColumnExprPrecedence3Context):
        if ctx.EQ_SINGLE() or ctx.EQ_DOUBLE():
            op = ast.CompareOperationType.Eq
        elif ctx.NOT_EQ():
            op = ast.CompareOperationType.NotEq
        elif ctx.LT():
            op = ast.CompareOperationType.Lt
        elif ctx.LE():
            op = ast.CompareOperationType.LtE
        elif ctx.GT():
            op = ast.CompareOperationType.Gt
        elif ctx.GE():
            op = ast.CompareOperationType.GtE
        elif ctx.LIKE():
            if ctx.NOT():
                op = ast.CompareOperationType.NotLike
            else:
                op = ast.CompareOperationType.Like
        elif ctx.ILIKE():
            if ctx.NOT():
                op = ast.CompareOperationType.NotILike
            else:
                op = ast.CompareOperationType.ILike
        elif ctx.IN():
            if ctx.GLOBAL():
                raise NotImplementedError(f"Unsupported node: IN GLOBAL")
            if ctx.NOT():
                op = ast.CompareOperationType.NotIn
            else:
                op = ast.CompareOperationType.In
        else:
            raise NotImplementedError(f"Unsupported ColumnExprPrecedence3: {ctx.getText()}")
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
            raise NotImplementedError(f"Unsupported interval type: {ctx.interval().getText()}")

        return ast.Call(name=name, args=[self.visit(ctx.columnExpr())])

    def visitColumnExprIsNull(self, ctx: HogQLParser.ColumnExprIsNullContext):
        return ast.CompareOperation(
            left=self.visit(ctx.columnExpr()),
            right=ast.Constant(value=None),
            op=ast.CompareOperationType.NotEq if ctx.NOT() else ast.CompareOperationType.Eq,
        )

    def visitColumnExprWinFunctionTarget(self, ctx: HogQLParser.ColumnExprWinFunctionTargetContext):
        raise NotImplementedError(f"Unsupported node: ColumnExprWinFunctionTarget")

    def visitColumnExprTrim(self, ctx: HogQLParser.ColumnExprTrimContext):
        raise NotImplementedError(f"Unsupported node: ColumnExprTrim")

    def visitColumnExprTuple(self, ctx: HogQLParser.ColumnExprTupleContext):
        raise NotImplementedError(f"Unsupported node: ColumnExprTuple")

    def visitColumnExprArrayAccess(self, ctx: HogQLParser.ColumnExprArrayAccessContext):
        object = self.visit(ctx.columnExpr(0))
        property = self.visit(ctx.columnExpr(1))
        if not isinstance(property, ast.Constant):
            raise NotImplementedError(f"Array access must be performed with a constant.")
        if isinstance(object, ast.Field):
            return ast.Field(chain=object.chain + [property.value])

        raise NotImplementedError(
            f"Unsupported combination for ColumnExprArrayAccess: {object.__class__.__name__}[{property.__class__.__name__}]"
        )

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
        raise NotImplementedError(f"Unsupported node: ColumnExprTupleAccess")

    def visitColumnExprCase(self, ctx: HogQLParser.ColumnExprCaseContext):
        raise NotImplementedError(f"Unsupported node: ColumnExprCase")

    def visitColumnExprDate(self, ctx: HogQLParser.ColumnExprDateContext):
        raise NotImplementedError(f"Unsupported node: ColumnExprDate")

    def visitColumnExprNot(self, ctx: HogQLParser.ColumnExprNotContext):
        return ast.Not(expr=self.visit(ctx.columnExpr()))

    def visitColumnExprWinFunction(self, ctx: HogQLParser.ColumnExprWinFunctionContext):
        raise NotImplementedError(f"Unsupported node: ColumnExprWinFunction")

    def visitColumnExprIdentifier(self, ctx: HogQLParser.ColumnExprIdentifierContext):
        return self.visit(ctx.columnIdentifier())

    def visitColumnExprFunction(self, ctx: HogQLParser.ColumnExprFunctionContext):
        if ctx.columnExprList():
            raise NotImplementedError(f"Functions that return functions are not supported")
        name = self.visit(ctx.identifier())
        args = self.visit(ctx.columnArgList()) if ctx.columnArgList() else []
        return ast.Call(name=name, args=args)

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
        raise NotImplementedError(f"Unsupported node: ColumnLambdaExpr")

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
            raise ValueError(f"Alias '{alias}' is a reserved keyword.")
        return ast.JoinExpr(table=self.visit(ctx.tableExpr()), alias=alias)

    def visitTableExprFunction(self, ctx: HogQLParser.TableExprFunctionContext):
        raise NotImplementedError(f"Unsupported node: TableExprFunction")

    def visitTableFunctionExpr(self, ctx: HogQLParser.TableFunctionExprContext):
        raise NotImplementedError(f"Unsupported node: TableFunctionExpr")

    def visitTableIdentifier(self, ctx: HogQLParser.TableIdentifierContext):
        text = self.visit(ctx.identifier())
        if ctx.databaseIdentifier():
            return [self.visit(ctx.databaseIdentifier()), text]
        return [text]

    def visitTableArgList(self, ctx: HogQLParser.TableArgListContext):
        raise NotImplementedError(f"Unsupported node: TableArgList")

    def visitTableArgExpr(self, ctx: HogQLParser.TableArgExprContext):
        raise NotImplementedError(f"Unsupported node: TableArgExpr")

    def visitDatabaseIdentifier(self, ctx: HogQLParser.DatabaseIdentifierContext):
        return self.visit(ctx.identifier())

    def visitFloatingLiteral(self, ctx: HogQLParser.FloatingLiteralContext):
        raise NotImplementedError(f"Unsupported node: visitFloatingLiteral")

    def visitNumberLiteral(self, ctx: HogQLParser.NumberLiteralContext):
        text = ctx.getText()
        if "." in text:
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
        raise NotImplementedError(f"Unsupported node: IdentifierOrNull")

    def visitEnumValue(self, ctx: HogQLParser.EnumValueContext):
        raise NotImplementedError(f"Unsupported node: EnumValue")
