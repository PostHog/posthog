from typing import Dict, Literal, Optional, cast

from antlr4 import CommonTokenStream, InputStream, ParseTreeVisitor
from antlr4.error.ErrorListener import ErrorListener

from posthog.hogql import ast
from posthog.hogql.grammar.HogQLLexer import HogQLLexer
from posthog.hogql.grammar.HogQLParser import HogQLParser
from posthog.hogql.parser_utils import parse_string_literal
from posthog.hogql.placeholders import replace_placeholders


def parse_expr(expr: str, placeholders: Optional[Dict[str, ast.Expr]] = None) -> ast.Expr:
    parse_tree = get_parser(expr).expr()
    node = HogQLParseTreeConverter().visit(parse_tree)
    if placeholders:
        node = replace_placeholders(node, placeholders)
    return node


def parse_select(statement: str, placeholders: Optional[Dict[str, ast.Expr]] = None) -> ast.Expr:
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
        select = self.visit(ctx.columnExprList()) if ctx.columnExprList() else []
        select_from = self.visit(ctx.fromClause()) if ctx.fromClause() else None
        where = self.visit(ctx.whereClause()) if ctx.whereClause() else None
        prewhere = self.visit(ctx.prewhereClause()) if ctx.prewhereClause() else None
        having = self.visit(ctx.havingClause()) if ctx.havingClause() else None
        group_by = self.visit(ctx.groupByClause()) if ctx.groupByClause() else None
        order_by = self.visit(ctx.orderByClause()) if ctx.orderByClause() else None

        limit = None
        offset = None
        if ctx.limitClause() and ctx.limitClause().limitExpr():
            limit_expr = ctx.limitClause().limitExpr()
            limit_node = self.visit(limit_expr.columnExpr(0))
            if limit_node is not None:
                if isinstance(limit_node, ast.Constant) and isinstance(limit_node.value, int):
                    limit = limit_node.value
                else:
                    raise Exception(f"LIMIT must be an integer")
            if limit_expr.columnExpr(1):
                offset_node = self.visit(limit_expr.columnExpr(1))
                if offset_node is not None:
                    if isinstance(offset_node, ast.Constant) and isinstance(offset_node.value, int):
                        offset = offset_node.value
                    else:
                        raise Exception(f"OFFSET must be an integer")

        if ctx.withClause():
            raise NotImplementedError(f"Unsupported: SelectStmt.withClause()")
        if ctx.topClause():
            raise NotImplementedError(f"Unsupported: SelectStmt.topClause()")
        if ctx.arrayJoinClause():
            raise NotImplementedError(f"Unsupported: SelectStmt.arrayJoinClause()")
        if ctx.windowClause():
            raise NotImplementedError(f"Unsupported: SelectStmt.windowClause()")
        if ctx.limitByClause():
            raise NotImplementedError(f"Unsupported: SelectStmt.limitByClause()")
        if ctx.settingsClause():
            raise NotImplementedError(f"Unsupported: SelectStmt.settingsClause()")

        return ast.SelectQuery(
            select=select,
            distinct=True if ctx.DISTINCT() else None,
            select_from=select_from,
            where=where,
            prewhere=prewhere,
            having=having,
            group_by=group_by,
            order_by=order_by,
            limit=limit,
            offset=offset,
        )

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

    def visitLimitByClause(self, ctx: HogQLParser.LimitByClauseContext):
        raise NotImplementedError(f"Unsupported node: LimitByClause")

    def visitLimitClause(self, ctx: HogQLParser.LimitClauseContext):
        raise Exception(f"Can not call visitLimitClause directly")

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
            join_type = f"{self.visit(ctx.joinOp())} JOIN"
        else:
            join_type = "JOIN"
        join_constraint = self.visit(ctx.joinConstraintClause())

        join_without_next_expr = join1
        while join_without_next_expr.join_expr:
            join_without_next_expr = join_without_next_expr.join_expr

        join_without_next_expr.join_expr = join2
        join_without_next_expr.join_constraint = join_constraint
        join_without_next_expr.join_type = join_type
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
        if ctx.LEFT():
            tokens.append("INNER")
        if ctx.ALL():
            tokens.append("ALL")
        if ctx.ANTI():
            tokens.append("ANTI")
        if ctx.ANY():
            tokens.append("ANY")
        if ctx.ASOF():
            tokens.append("ASOF")
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
        raise Exception(f"Can not call visitLimitExpr directly")

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
        return ast.Alias(expr=expr, alias=alias)

    def visitColumnExprExtract(self, ctx: HogQLParser.ColumnExprExtractContext):
        raise NotImplementedError(f"Unsupported node: ColumnExprExtract")

    def visitColumnExprNegate(self, ctx: HogQLParser.ColumnExprNegateContext):
        raise NotImplementedError(f"Unsupported node: ColumnExprNegate")

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
        raise NotImplementedError(f"Unsupported node: ColumnExprInterval")

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
        chain = [self.visit(identifier) for identifier in ctx.identifier()]
        return chain

    def visitTableExprIdentifier(self, ctx: HogQLParser.TableExprIdentifierContext):
        chain = self.visit(ctx.tableIdentifier())
        return ast.Field(chain=chain)

    def visitTableExprSubquery(self, ctx: HogQLParser.TableExprSubqueryContext):
        return self.visit(ctx.selectUnionStmt())

    def visitTableExprAlias(self, ctx: HogQLParser.TableExprAliasContext):
        return ast.JoinExpr(table=self.visit(ctx.tableExpr()), alias=self.visit(ctx.alias() or ctx.identifier()))

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
        if len(text) >= 2 and text.startswith("`") and text.endswith("`"):
            text = parse_string_literal(ctx)
        return text

    def visitIdentifier(self, ctx: HogQLParser.IdentifierContext):
        text = ctx.getText()
        if len(text) >= 2 and text.startswith("`") and text.endswith("`"):
            text = parse_string_literal(ctx)
        return text

    def visitIdentifierOrNull(self, ctx: HogQLParser.IdentifierOrNullContext):
        raise NotImplementedError(f"Unsupported node: IdentifierOrNull")

    def visitEnumValue(self, ctx: HogQLParser.EnumValueContext):
        raise NotImplementedError(f"Unsupported node: EnumValue")
