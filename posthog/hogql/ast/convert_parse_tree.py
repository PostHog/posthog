from antlr4 import ParseTreeVisitor
from antlr4.tree.Tree import ParseTree

from posthog.hogql.ast import ast
from posthog.hogql.grammar.HogQLParser import HogQLParser


def convert_parse_tree(parse_tree: ParseTree) -> ast.AST:
    return HogQLParseTreeConverter().visit(parse_tree)


def parse_tree_to_expr(parse_tree: ParseTree) -> ast.Expr:
    response = HogQLParseTreeConverter().visit(parse_tree)
    # TODO: raise if not expr
    return response


class HogQLParseTreeConverter(ParseTreeVisitor):
    def visitQueryStmt(self, ctx: HogQLParser.QueryStmtContext):
        raise Exception(f"Unsupported node: QueryStmt")

    def visitQuery(self, ctx: HogQLParser.QueryContext):
        raise Exception(f"Unsupported node: Query")

    def visitCtes(self, ctx: HogQLParser.CtesContext):
        raise Exception(f"Unsupported node: Ctes")

    def visitNamedQuery(self, ctx: HogQLParser.NamedQueryContext):
        raise Exception(f"Unsupported node: NamedQuery")

    def visitColumnAliases(self, ctx: HogQLParser.ColumnAliasesContext):
        raise Exception(f"Unsupported node: ColumnAliases")

    def visitSelectUnionStmt(self, ctx: HogQLParser.SelectUnionStmtContext):
        raise Exception(f"Unsupported node: SelectUnionStmt")

    def visitSelectStmtWithParens(self, ctx: HogQLParser.SelectStmtWithParensContext):
        raise Exception(f"Unsupported node: SelectStmtWithParens")

    def visitSelectStmt(self, ctx: HogQLParser.SelectStmtContext):
        raise Exception(f"Unsupported node: SelectStmt")

    def visitWithClause(self, ctx: HogQLParser.WithClauseContext):
        raise Exception(f"Unsupported node: WithClause")

    def visitTopClause(self, ctx: HogQLParser.TopClauseContext):
        raise Exception(f"Unsupported node: TopClause")

    def visitFromClause(self, ctx: HogQLParser.FromClauseContext):
        raise Exception(f"Unsupported node: FromClause")

    def visitArrayJoinClause(self, ctx: HogQLParser.ArrayJoinClauseContext):
        raise Exception(f"Unsupported node: ArrayJoinClause")

    def visitWindowClause(self, ctx: HogQLParser.WindowClauseContext):
        raise Exception(f"Unsupported node: WindowClause")

    def visitPrewhereClause(self, ctx: HogQLParser.PrewhereClauseContext):
        raise Exception(f"Unsupported node: PrewhereClause")

    def visitWhereClause(self, ctx: HogQLParser.WhereClauseContext):
        raise Exception(f"Unsupported node: WhereClause")

    def visitGroupByClause(self, ctx: HogQLParser.GroupByClauseContext):
        raise Exception(f"Unsupported node: GroupByClause")

    def visitHavingClause(self, ctx: HogQLParser.HavingClauseContext):
        raise Exception(f"Unsupported node: HavingClause")

    def visitOrderByClause(self, ctx: HogQLParser.OrderByClauseContext):
        raise Exception(f"Unsupported node: OrderByClause")

    def visitProjectionOrderByClause(self, ctx: HogQLParser.ProjectionOrderByClauseContext):
        raise Exception(f"Unsupported node: ProjectionOrderByClause")

    def visitLimitByClause(self, ctx: HogQLParser.LimitByClauseContext):
        raise Exception(f"Unsupported node: LimitByClause")

    def visitLimitClause(self, ctx: HogQLParser.LimitClauseContext):
        raise Exception(f"Unsupported node: LimitClause")

    def visitSettingsClause(self, ctx: HogQLParser.SettingsClauseContext):
        raise Exception(f"Unsupported node: SettingsClause")

    def visitJoinExprOp(self, ctx: HogQLParser.JoinExprOpContext):
        raise Exception(f"Unsupported node: JoinExprOp")

    def visitJoinExprTable(self, ctx: HogQLParser.JoinExprTableContext):
        raise Exception(f"Unsupported node: JoinExprTable")

    def visitJoinExprParens(self, ctx: HogQLParser.JoinExprParensContext):
        raise Exception(f"Unsupported node: JoinExprParens")

    def visitJoinExprCrossOp(self, ctx: HogQLParser.JoinExprCrossOpContext):
        raise Exception(f"Unsupported node: JoinExprCrossOp")

    def visitJoinOpInner(self, ctx: HogQLParser.JoinOpInnerContext):
        raise Exception(f"Unsupported node: JoinOpInner")

    def visitJoinOpLeftRight(self, ctx: HogQLParser.JoinOpLeftRightContext):
        raise Exception(f"Unsupported node: JoinOpLeftRight")

    def visitJoinOpFull(self, ctx: HogQLParser.JoinOpFullContext):
        raise Exception(f"Unsupported node: JoinOpFull")

    def visitJoinOpCross(self, ctx: HogQLParser.JoinOpCrossContext):
        raise Exception(f"Unsupported node: JoinOpCross")

    def visitJoinConstraintClause(self, ctx: HogQLParser.JoinConstraintClauseContext):
        raise Exception(f"Unsupported node: JoinConstraintClause")

    def visitSampleClause(self, ctx: HogQLParser.SampleClauseContext):
        raise Exception(f"Unsupported node: SampleClause")

    def visitLimitExpr(self, ctx: HogQLParser.LimitExprContext):
        raise Exception(f"Unsupported node: LimitExpr")

    def visitOrderExprList(self, ctx: HogQLParser.OrderExprListContext):
        raise Exception(f"Unsupported node: OrderExprList")

    def visitOrderExpr(self, ctx: HogQLParser.OrderExprContext):
        raise Exception(f"Unsupported node: OrderExpr")

    def visitRatioExpr(self, ctx: HogQLParser.RatioExprContext):
        raise Exception(f"Unsupported node: RatioExpr")

    def visitSettingExprList(self, ctx: HogQLParser.SettingExprListContext):
        raise Exception(f"Unsupported node: SettingExprList")

    def visitSettingExpr(self, ctx: HogQLParser.SettingExprContext):
        raise Exception(f"Unsupported node: SettingExpr")

    def visitWindowExpr(self, ctx: HogQLParser.WindowExprContext):
        raise Exception(f"Unsupported node: WindowExpr")

    def visitWinPartitionByClause(self, ctx: HogQLParser.WinPartitionByClauseContext):
        raise Exception(f"Unsupported node: WinPartitionByClause")

    def visitWinOrderByClause(self, ctx: HogQLParser.WinOrderByClauseContext):
        raise Exception(f"Unsupported node: WinOrderByClause")

    def visitWinFrameClause(self, ctx: HogQLParser.WinFrameClauseContext):
        raise Exception(f"Unsupported node: WinFrameClause")

    def visitFrameStart(self, ctx: HogQLParser.FrameStartContext):
        raise Exception(f"Unsupported node: FrameStart")

    def visitFrameBetween(self, ctx: HogQLParser.FrameBetweenContext):
        raise Exception(f"Unsupported node: FrameBetween")

    def visitWinFrameBound(self, ctx: HogQLParser.WinFrameBoundContext):
        raise Exception(f"Unsupported node: WinFrameBound")

    def visitColumnTypeExprSimple(self, ctx: HogQLParser.ColumnTypeExprSimpleContext):
        raise Exception(f"Unsupported node: ColumnTypeExprSimple")

    def visitColumnTypeExprNested(self, ctx: HogQLParser.ColumnTypeExprNestedContext):
        raise Exception(f"Unsupported node: ColumnTypeExprNested")

    def visitColumnTypeExprEnum(self, ctx: HogQLParser.ColumnTypeExprEnumContext):
        raise Exception(f"Unsupported node: ColumnTypeExprEnum")

    def visitColumnTypeExprComplex(self, ctx: HogQLParser.ColumnTypeExprComplexContext):
        raise Exception(f"Unsupported node: ColumnTypeExprComplex")

    def visitColumnTypeExprParam(self, ctx: HogQLParser.ColumnTypeExprParamContext):
        raise Exception(f"Unsupported node: ColumnTypeExprParam")

    def visitColumnExprList(self, ctx: HogQLParser.ColumnExprListContext):
        raise Exception(f"Unsupported node: ColumnExprList")

    def visitColumnsExprAsterisk(self, ctx: HogQLParser.ColumnsExprAsteriskContext):
        raise Exception(f"Unsupported node: ColumnsExprAsterisk")

    def visitColumnsExprSubquery(self, ctx: HogQLParser.ColumnsExprSubqueryContext):
        raise Exception(f"Unsupported node: ColumnsExprSubquery")

    def visitColumnsExprColumn(self, ctx: HogQLParser.ColumnsExprColumnContext):
        raise Exception(f"Unsupported node: ColumnsExprColumn")

    def visitColumnExprTernaryOp(self, ctx: HogQLParser.ColumnExprTernaryOpContext):
        raise Exception(f"Unsupported node: ColumnExprTernaryOp")

    def visitColumnExprAlias(self, ctx: HogQLParser.ColumnExprAliasContext):
        raise Exception(f"Unsupported node: ColumnExprAlias")

    def visitColumnExprExtract(self, ctx: HogQLParser.ColumnExprExtractContext):
        raise Exception(f"Unsupported node: ColumnExprExtract")

    def visitColumnExprNegate(self, ctx: HogQLParser.ColumnExprNegateContext):
        raise Exception(f"Unsupported node: ColumnExprNegate")

    def visitColumnExprSubquery(self, ctx: HogQLParser.ColumnExprSubqueryContext):
        raise Exception(f"Unsupported node: ColumnExprSubquery")

    def visitColumnExprLiteral(self, ctx: HogQLParser.ColumnExprLiteralContext):
        if len(ctx.children) == 1:
            return self.visit(ctx.children[0])
        return self.visitChildren(ctx)

    def visitColumnExprArray(self, ctx: HogQLParser.ColumnExprArrayContext):
        raise Exception(f"Unsupported node: ColumnExprArray")

    def visitColumnExprSubstring(self, ctx: HogQLParser.ColumnExprSubstringContext):
        raise Exception(f"Unsupported node: ColumnExprSubstring")

    def visitColumnExprCast(self, ctx: HogQLParser.ColumnExprCastContext):
        raise Exception(f"Unsupported node: ColumnExprCast")

    def visitColumnExprOr(self, ctx: HogQLParser.ColumnExprOrContext):
        return ast.BooleanOperation(
            left=self.visit(ctx.columnExpr(0)),
            right=self.visit(ctx.columnExpr(1)),
            op=ast.BooleanOperationType.Or,
        )

    def visitColumnExprPrecedence1(self, ctx: HogQLParser.ColumnExprPrecedence1Context):
        if ctx.SLASH():
            op = ast.BinaryOperationType.Div
        elif ctx.ASTERISK():
            op = ast.BinaryOperationType.Mult
        elif ctx.PERCENT():
            op = ast.BinaryOperationType.Mod
        else:
            raise Exception(f"Unsupported ColumnExprPrecedence1: {ctx.operator.text}")
        return ast.BinaryOperation(left=self.visit(ctx.left), right=self.visit(ctx.right), op=op)

    def visitColumnExprPrecedence2(self, ctx: HogQLParser.ColumnExprPrecedence2Context):
        if ctx.PLUS():
            op = ast.BinaryOperationType.Add
        elif ctx.DASH():
            op = ast.BinaryOperationType.Sub
        elif ctx.CONCAT():
            raise Exception(f"Yet unsupported text concat operation: {ctx.operator.text}")
        else:
            raise Exception(f"Unsupported ColumnExprPrecedence2: {ctx.operator.text}")
        return ast.BinaryOperation(left=self.visit(ctx.left), right=self.visit(ctx.right), op=op)

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
            raise Exception(f"Unsupported ColumnExprPrecedence3: {ctx.getText()}")
        return ast.CompareOperation(left=self.visit(ctx.left), right=self.visit(ctx.right), op=op)

    def visitColumnExprInterval(self, ctx: HogQLParser.ColumnExprIntervalContext):
        raise Exception(f"Unsupported node: ColumnExprInterval")

    def visitColumnExprIsNull(self, ctx: HogQLParser.ColumnExprIsNullContext):
        return ast.CompareOperation(
            left=self.visit(ctx.columnExpr()),
            right=ast.Constant(value=None),
            op=ast.CompareOperationType.NotEq if ctx.NOT() else ast.CompareOperationType.Eq,
        )

    def visitColumnExprWinFunctionTarget(self, ctx: HogQLParser.ColumnExprWinFunctionTargetContext):
        raise Exception(f"Unsupported node: ColumnExprWinFunctionTarget")

    def visitColumnExprTrim(self, ctx: HogQLParser.ColumnExprTrimContext):
        raise Exception(f"Unsupported node: ColumnExprTrim")

    def visitColumnExprTuple(self, ctx: HogQLParser.ColumnExprTupleContext):
        raise Exception(f"Unsupported node: ColumnExprTuple")

    def visitColumnExprArrayAccess(self, ctx: HogQLParser.ColumnExprArrayAccessContext):
        raise Exception(f"Unsupported node: ColumnExprArrayAccess")

    def visitColumnExprBetween(self, ctx: HogQLParser.ColumnExprBetweenContext):
        raise Exception(f"Unsupported node: ColumnExprBetween")

    def visitColumnExprParens(self, ctx: HogQLParser.ColumnExprParensContext):
        return ast.Parens(expr=self.visit(ctx.columnExpr()))

    def visitColumnExprTimestamp(self, ctx: HogQLParser.ColumnExprTimestampContext):
        raise Exception(f"Unsupported node: ColumnExprTimestamp")

    def visitColumnExprAnd(self, ctx: HogQLParser.ColumnExprAndContext):
        return ast.BooleanOperation(
            left=self.visit(ctx.columnExpr(0)),
            right=self.visit(ctx.columnExpr(1)),
            op=ast.BooleanOperationType.And,
        )

    def visitColumnExprTupleAccess(self, ctx: HogQLParser.ColumnExprTupleAccessContext):
        raise Exception(f"Unsupported node: ColumnExprTupleAccess")

    def visitColumnExprCase(self, ctx: HogQLParser.ColumnExprCaseContext):
        raise Exception(f"Unsupported node: ColumnExprCase")

    def visitColumnExprDate(self, ctx: HogQLParser.ColumnExprDateContext):
        raise Exception(f"Unsupported node: ColumnExprDate")

    def visitColumnExprNot(self, ctx: HogQLParser.ColumnExprNotContext):
        return ast.NotOperation(expr=self.visit(ctx.columnExpr()))

    def visitColumnExprWinFunction(self, ctx: HogQLParser.ColumnExprWinFunctionContext):
        raise Exception(f"Unsupported node: ColumnExprWinFunction")

    def visitColumnExprIdentifier(self, ctx: HogQLParser.ColumnExprIdentifierContext):
        return self.visitChildren(ctx)

    def visitColumnExprFunction(self, ctx: HogQLParser.ColumnExprFunctionContext):
        raise Exception(f"Unsupported node: ColumnExprFunction")

    def visitColumnExprAsterisk(self, ctx: HogQLParser.ColumnExprAsteriskContext):
        raise Exception(f"Unsupported node: ColumnExprAsterisk")

    def visitColumnArgList(self, ctx: HogQLParser.ColumnArgListContext):
        raise Exception(f"Unsupported node: ColumnArgList")

    def visitColumnArgExpr(self, ctx: HogQLParser.ColumnArgExprContext):
        raise Exception(f"Unsupported node: ColumnArgExpr")

    def visitColumnLambdaExpr(self, ctx: HogQLParser.ColumnLambdaExprContext):
        raise Exception(f"Unsupported node: ColumnLambdaExpr")

    def visitColumnIdentifier(self, ctx: HogQLParser.ColumnIdentifierContext):
        table = self.visit(ctx.tableIdentifier()) if ctx.tableIdentifier() else None
        nested = self.visit(ctx.nestedIdentifier())

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
            raise Exception(f"Unsupported property access: {ctx.getText()}")

        if isinstance(nested, ast.FieldAccess):
            chain.append(nested.field)
        elif isinstance(nested, ast.FieldAccessChain):
            chain.extend(nested.chain)
        else:
            raise Exception(f"Unsupported property access: {ctx.getText()}")

        return ast.FieldAccessChain(chain=chain)

    def visitNestedIdentifier(self, ctx: HogQLParser.NestedIdentifierContext):
        chain = [identifier.getText() for identifier in ctx.identifier()]
        if len(chain) == 1:
            return ast.FieldAccess(field=chain[0])
        return ast.FieldAccessChain(chain=chain)

    def visitTableExprIdentifier(self, ctx: HogQLParser.TableExprIdentifierContext):
        raise Exception(f"Unsupported node: TableExprIdentifier")

    def visitTableExprSubquery(self, ctx: HogQLParser.TableExprSubqueryContext):
        raise Exception(f"Unsupported node: TableExprSubquery")

    def visitTableExprAlias(self, ctx: HogQLParser.TableExprAliasContext):
        raise Exception(f"Unsupported node: TableExprAlias")

    def visitTableExprFunction(self, ctx: HogQLParser.TableExprFunctionContext):
        raise Exception(f"Unsupported node: TableExprFunction")

    def visitTableFunctionExpr(self, ctx: HogQLParser.TableFunctionExprContext):
        raise Exception(f"Unsupported node: TableFunctionExpr")

    def visitTableIdentifier(self, ctx: HogQLParser.TableIdentifierContext):
        identifier = ctx.identifier().getText()
        if ctx.databaseIdentifier():
            return ast.FieldAccessChain(chain=[ctx.databaseIdentifier().getText(), identifier])
        return ast.FieldAccess(field=identifier)

    def visitTableArgList(self, ctx: HogQLParser.TableArgListContext):
        raise Exception(f"Unsupported node: TableArgList")

    def visitTableArgExpr(self, ctx: HogQLParser.TableArgExprContext):
        raise Exception(f"Unsupported node: TableArgExpr")

    def visitDatabaseIdentifier(self, ctx: HogQLParser.DatabaseIdentifierContext):
        return ast.FieldAccess(field=ctx.identifier().getText())

    def visitFloatingLiteral(self, ctx: HogQLParser.FloatingLiteralContext):
        raise Exception(f"Unsupported node: visitFloatingLiteral")
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
            text = ctx.getText()
            text = text[1:-1]
            text = text.replace("''", "'")
            return ast.Constant(value=text)
        return self.visitChildren(ctx)

    def visitInterval(self, ctx: HogQLParser.IntervalContext):
        raise Exception(f"Unsupported node: Interval")

    def visitKeyword(self, ctx: HogQLParser.KeywordContext):
        raise Exception(f"Unsupported node: Keyword")

    def visitKeywordForAlias(self, ctx: HogQLParser.KeywordForAliasContext):
        raise Exception(f"Unsupported node: KeywordForAlias")

    def visitAlias(self, ctx: HogQLParser.AliasContext):
        raise Exception(f"Unsupported node: Alias")

    def visitIdentifier(self, ctx: HogQLParser.IdentifierContext):
        return ast.FieldAccess(field=ctx.getText())

    def visitIdentifierOrNull(self, ctx: HogQLParser.IdentifierOrNullContext):
        raise Exception(f"Unsupported node: IdentifierOrNull")

    def visitEnumValue(self, ctx: HogQLParser.EnumValueContext):
        raise Exception(f"Unsupported node: EnumValue")
