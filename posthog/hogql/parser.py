from antlr4 import CommonTokenStream, InputStream, ParseTreeVisitor
from antlr4.error.ErrorListener import ErrorListener

from posthog.hogql import ast
from posthog.hogql.grammar.HogQLLexer import HogQLLexer
from posthog.hogql.grammar.HogQLParser import HogQLParser
from posthog.hogql.parser_utils import parse_string_literal


def parse_expr(expr: str) -> ast.Expr:
    parse_tree = get_parser(expr).column()
    return HogQLParseTreeConverter().visit(parse_tree)


def parse_statement(statement: str) -> ast.Expr:
    parse_tree = get_parser(statement).selectQuery()
    return HogQLParseTreeConverter().visit(parse_tree)


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
    def visitSelectQuery(self, ctx: HogQLParser.SelectQueryContext):
        return self.visit(ctx.selectUnionStmt() or ctx.selectStmt())

    def visitSelectUnionStmt(self, ctx: HogQLParser.SelectUnionStmtContext):
        selects = ctx.selectStmtWithParens()
        if len(selects) != 1:
            raise NotImplementedError(f"Unsupported: UNION ALL")

        return self.visit(selects[0])

    def visitSelectStmtWithParens(self, ctx: HogQLParser.SelectStmtWithParensContext):
        return self.visit(ctx.selectStmt() or ctx.selectUnionStmt())

    def visitSelectStmt(self, ctx: HogQLParser.SelectStmtContext):
        columns = [self.visit(column) for column in ctx.columnExprList().columnsExpr()] if ctx.columnExprList() else []
        columns = [column if isinstance(column, ast.Column) else ast.Column(expr=column) for column in columns]
        where = self.visit(ctx.whereClause()) if ctx.whereClause() else None
        prewhere = self.visit(ctx.prewhereClause()) if ctx.prewhereClause() else None
        having = self.visit(ctx.havingClause()) if ctx.havingClause() else None

        if ctx.withClause():
            raise NotImplementedError(f"Unsupported: SelectStmt.withClause()")
        if ctx.topClause():
            raise NotImplementedError(f"Unsupported: SelectStmt.topClause()")
        if ctx.fromClause():
            raise NotImplementedError(f"Unsupported: SelectStmt.fromClause()")
        if ctx.arrayJoinClause():
            raise NotImplementedError(f"Unsupported: SelectStmt.arrayJoinClause()")
        if ctx.windowClause():
            raise NotImplementedError(f"Unsupported: SelectStmt.windowClause()")
        if ctx.groupByClause():
            raise NotImplementedError(f"Unsupported: SelectStmt.groupByClause()")
        if ctx.orderByClause():
            raise NotImplementedError(f"Unsupported: SelectStmt.orderByClause()")
        if ctx.limitByClause():
            raise NotImplementedError(f"Unsupported: SelectStmt.limitByClause()")
        if ctx.limitClause():
            raise NotImplementedError(f"Unsupported: SelectStmt.limitClause()")
        if ctx.settingsClause():
            raise NotImplementedError(f"Unsupported: SelectStmt.settingsClause()")

        return ast.Select(
            columns=columns,
            where=where,
            prewhere=prewhere,
            having=having,
        )

    def visitWithClause(self, ctx: HogQLParser.WithClauseContext):
        raise NotImplementedError(f"Unsupported node: WithClause")

    def visitTopClause(self, ctx: HogQLParser.TopClauseContext):
        raise NotImplementedError(f"Unsupported node: TopClause")

    def visitFromClause(self, ctx: HogQLParser.FromClauseContext):
        raise NotImplementedError(f"Unsupported node: FromClause")

    def visitArrayJoinClause(self, ctx: HogQLParser.ArrayJoinClauseContext):
        raise NotImplementedError(f"Unsupported node: ArrayJoinClause")

    def visitWindowClause(self, ctx: HogQLParser.WindowClauseContext):
        raise NotImplementedError(f"Unsupported node: WindowClause")

    def visitPrewhereClause(self, ctx: HogQLParser.PrewhereClauseContext):
        return self.visit(ctx.columnExpr())

    def visitWhereClause(self, ctx: HogQLParser.WhereClauseContext):
        return self.visit(ctx.columnExpr())

    def visitGroupByClause(self, ctx: HogQLParser.GroupByClauseContext):
        raise NotImplementedError(f"Unsupported node: GroupByClause")

    def visitHavingClause(self, ctx: HogQLParser.HavingClauseContext):
        return self.visit(ctx.columnExpr())

    def visitOrderByClause(self, ctx: HogQLParser.OrderByClauseContext):
        raise NotImplementedError(f"Unsupported node: OrderByClause")

    def visitProjectionOrderByClause(self, ctx: HogQLParser.ProjectionOrderByClauseContext):
        raise NotImplementedError(f"Unsupported node: ProjectionOrderByClause")

    def visitLimitByClause(self, ctx: HogQLParser.LimitByClauseContext):
        raise NotImplementedError(f"Unsupported node: LimitByClause")

    def visitLimitClause(self, ctx: HogQLParser.LimitClauseContext):
        raise NotImplementedError(f"Unsupported node: LimitClause")

    def visitSettingsClause(self, ctx: HogQLParser.SettingsClauseContext):
        raise NotImplementedError(f"Unsupported node: SettingsClause")

    def visitJoinExprOp(self, ctx: HogQLParser.JoinExprOpContext):
        raise NotImplementedError(f"Unsupported node: JoinExprOp")

    def visitJoinExprTable(self, ctx: HogQLParser.JoinExprTableContext):
        raise NotImplementedError(f"Unsupported node: JoinExprTable")

    def visitJoinExprParens(self, ctx: HogQLParser.JoinExprParensContext):
        raise NotImplementedError(f"Unsupported node: JoinExprParens")

    def visitJoinExprCrossOp(self, ctx: HogQLParser.JoinExprCrossOpContext):
        raise NotImplementedError(f"Unsupported node: JoinExprCrossOp")

    def visitJoinOpInner(self, ctx: HogQLParser.JoinOpInnerContext):
        raise NotImplementedError(f"Unsupported node: JoinOpInner")

    def visitJoinOpLeftRight(self, ctx: HogQLParser.JoinOpLeftRightContext):
        raise NotImplementedError(f"Unsupported node: JoinOpLeftRight")

    def visitJoinOpFull(self, ctx: HogQLParser.JoinOpFullContext):
        raise NotImplementedError(f"Unsupported node: JoinOpFull")

    def visitJoinOpCross(self, ctx: HogQLParser.JoinOpCrossContext):
        raise NotImplementedError(f"Unsupported node: JoinOpCross")

    def visitJoinConstraintClause(self, ctx: HogQLParser.JoinConstraintClauseContext):
        raise NotImplementedError(f"Unsupported node: JoinConstraintClause")

    def visitSampleClause(self, ctx: HogQLParser.SampleClauseContext):
        raise NotImplementedError(f"Unsupported node: SampleClause")

    def visitLimitExpr(self, ctx: HogQLParser.LimitExprContext):
        raise NotImplementedError(f"Unsupported node: LimitExpr")

    def visitOrderExprList(self, ctx: HogQLParser.OrderExprListContext):
        raise NotImplementedError(f"Unsupported node: OrderExprList")

    def visitOrderExpr(self, ctx: HogQLParser.OrderExprContext):
        raise NotImplementedError(f"Unsupported node: OrderExpr")

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
        raise NotImplementedError(f"Unsupported node: ColumnExprList")

    def visitColumnsExprAsterisk(self, ctx: HogQLParser.ColumnsExprAsteriskContext):
        raise NotImplementedError(f"Unsupported node: ColumnsExprAsterisk")

    def visitColumnsExprSubquery(self, ctx: HogQLParser.ColumnsExprSubqueryContext):
        return self.visit(ctx.selectUnionStmt())

    def visitColumnsExprColumn(self, ctx: HogQLParser.ColumnsExprColumnContext):
        return self.visit(ctx.columnExpr())

    def visitColumnExprTernaryOp(self, ctx: HogQLParser.ColumnExprTernaryOpContext):
        raise NotImplementedError(f"Unsupported node: ColumnExprTernaryOp")

    def visitColumnExprWithComment(self, ctx: HogQLParser.ColumnExprWithCommentContext):
        return self.visit(ctx.columnExpr())

    def visitColumnExprAlias(self, ctx: HogQLParser.ColumnExprAliasContext):
        if ctx.alias():
            alias = ctx.alias().getText()
        elif ctx.identifier():
            alias = ctx.identifier().getText()
        elif ctx.STRING_LITERAL():
            alias = parse_string_literal(ctx.STRING_LITERAL())
        else:
            raise NotImplementedError(f"Must specify an alias.")
        expr = self.visit(ctx.columnExpr())
        return ast.Column(expr=expr, alias=alias)

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
        else:
            # TODO: support "in", "not in", "global in", "global not in"
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
        if isinstance(object, ast.FieldAccess):
            return ast.FieldAccessChain(chain=[object.field, property.value])
        if isinstance(object, ast.FieldAccessChain):
            return ast.FieldAccessChain(chain=object.chain + [property.value])

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
        if isinstance(left, ast.BooleanOperation) and left.op == ast.BooleanOperationType.And:
            left_array = left.values
        else:
            left_array = [left]

        right = self.visit(ctx.columnExpr(1))
        if isinstance(right, ast.BooleanOperation) and right.op == ast.BooleanOperationType.And:
            right_array = right.values
        else:
            right_array = [right]

        return ast.BooleanOperation(
            values=left_array + right_array,
            op=ast.BooleanOperationType.And,
        )

    def visitColumnExprOr(self, ctx: HogQLParser.ColumnExprOrContext):
        left = self.visit(ctx.columnExpr(0))
        if isinstance(left, ast.BooleanOperation) and left.op == ast.BooleanOperationType.Or:
            left_array = left.values
        else:
            left_array = [left]

        right = self.visit(ctx.columnExpr(1))
        if isinstance(right, ast.BooleanOperation) and right.op == ast.BooleanOperationType.Or:
            right_array = right.values
        else:
            right_array = [right]

        return ast.BooleanOperation(
            values=left_array + right_array,
            op=ast.BooleanOperationType.Or,
        )

    def visitColumnExprTupleAccess(self, ctx: HogQLParser.ColumnExprTupleAccessContext):
        raise NotImplementedError(f"Unsupported node: ColumnExprTupleAccess")

    def visitColumnExprCase(self, ctx: HogQLParser.ColumnExprCaseContext):
        raise NotImplementedError(f"Unsupported node: ColumnExprCase")

    def visitColumnExprDate(self, ctx: HogQLParser.ColumnExprDateContext):
        raise NotImplementedError(f"Unsupported node: ColumnExprDate")

    def visitColumnExprNot(self, ctx: HogQLParser.ColumnExprNotContext):
        return ast.NotOperation(expr=self.visit(ctx.columnExpr()))

    def visitColumnExprWinFunction(self, ctx: HogQLParser.ColumnExprWinFunctionContext):
        raise NotImplementedError(f"Unsupported node: ColumnExprWinFunction")

    def visitColumnExprIdentifier(self, ctx: HogQLParser.ColumnExprIdentifierContext):
        return self.visitChildren(ctx)

    def visitColumnExprFunction(self, ctx: HogQLParser.ColumnExprFunctionContext):
        if ctx.columnExprList():
            raise NotImplementedError(f"Functions that return functions are not supported")
        name = ctx.identifier().getText()
        args = self.visit(ctx.columnArgList()) if ctx.columnArgList() else []
        return ast.Call(name=name, args=args)

    def visitColumnExprAsterisk(self, ctx: HogQLParser.ColumnExprAsteriskContext):
        raise NotImplementedError(f"Unsupported node: ColumnExprAsterisk")

    def visitColumnArgList(self, ctx: HogQLParser.ColumnArgListContext):
        return [self.visit(arg) for arg in ctx.columnArgExpr()]

    def visitColumnArgExpr(self, ctx: HogQLParser.ColumnArgExprContext):
        return self.visitChildren(ctx)

    def visitColumnLambdaExpr(self, ctx: HogQLParser.ColumnLambdaExprContext):
        raise NotImplementedError(f"Unsupported node: ColumnLambdaExpr")

    def visitColumnIdentifier(self, ctx: HogQLParser.ColumnIdentifierContext):
        table = self.visit(ctx.tableIdentifier()) if ctx.tableIdentifier() else None
        nested = self.visit(ctx.nestedIdentifier()) if ctx.nestedIdentifier() else None

        if table is None:
            if isinstance(nested, ast.FieldAccess):
                text = ctx.getText().lower()
                if text == "true":
                    return ast.Constant(value=True)
                if text == "false":
                    return ast.Constant(value=False)
            return nested

        chain = []
        if isinstance(table, ast.FieldAccess):
            chain.append(table.field)
        elif isinstance(table, ast.FieldAccessChain):
            chain.extend(table.chain)
        else:
            raise NotImplementedError(f"Unsupported property access: {ctx.getText()}")

        if isinstance(nested, ast.FieldAccess):
            chain.append(nested.field)
        elif isinstance(nested, ast.FieldAccessChain):
            chain.extend(nested.chain)
        else:
            raise NotImplementedError(f"Unsupported property access: {ctx.getText()}")

        return ast.FieldAccessChain(chain=chain)

    def visitNestedIdentifier(self, ctx: HogQLParser.NestedIdentifierContext):
        chain = [identifier.getText() for identifier in ctx.identifier()]
        if len(chain) == 1:
            return ast.FieldAccess(field=chain[0])
        return ast.FieldAccessChain(chain=chain)

    def visitTableExprIdentifier(self, ctx: HogQLParser.TableExprIdentifierContext):
        raise NotImplementedError(f"Unsupported node: TableExprIdentifier")

    def visitTableExprSubquery(self, ctx: HogQLParser.TableExprSubqueryContext):
        raise NotImplementedError(f"Unsupported node: TableExprSubquery")

    def visitTableExprAlias(self, ctx: HogQLParser.TableExprAliasContext):
        raise NotImplementedError(f"Unsupported node: TableExprAlias")

    def visitTableExprFunction(self, ctx: HogQLParser.TableExprFunctionContext):
        raise NotImplementedError(f"Unsupported node: TableExprFunction")

    def visitTableFunctionExpr(self, ctx: HogQLParser.TableFunctionExprContext):
        raise NotImplementedError(f"Unsupported node: TableFunctionExpr")

    def visitTableIdentifier(self, ctx: HogQLParser.TableIdentifierContext):
        identifier = ctx.identifier().getText()
        if ctx.databaseIdentifier():
            return ast.FieldAccessChain(chain=[ctx.databaseIdentifier().getText(), identifier])
        return ast.FieldAccess(field=identifier)

    def visitTableArgList(self, ctx: HogQLParser.TableArgListContext):
        raise NotImplementedError(f"Unsupported node: TableArgList")

    def visitTableArgExpr(self, ctx: HogQLParser.TableArgExprContext):
        raise NotImplementedError(f"Unsupported node: TableArgExpr")

    def visitDatabaseIdentifier(self, ctx: HogQLParser.DatabaseIdentifierContext):
        return ast.FieldAccess(field=ctx.identifier().getText())

    def visitFloatingLiteral(self, ctx: HogQLParser.FloatingLiteralContext):
        raise NotImplementedError(f"Unsupported node: visitFloatingLiteral")
        # return ast.Constant(value=float(ctx.getText()))

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
        raise NotImplementedError(f"Unsupported node: Alias")

    def visitIdentifier(self, ctx: HogQLParser.IdentifierContext):
        return ast.FieldAccess(field=ctx.getText())

    def visitIdentifierOrNull(self, ctx: HogQLParser.IdentifierOrNullContext):
        raise NotImplementedError(f"Unsupported node: IdentifierOrNull")

    def visitEnumValue(self, ctx: HogQLParser.EnumValueContext):
        raise NotImplementedError(f"Unsupported node: EnumValue")
