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
        # return self.visitChildren(ctx)

    def visitQuery(self, ctx: HogQLParser.QueryContext):
        raise Exception(f"Unsupported node: Query")
        # return self.visitChildren(ctx)

    def visitCtes(self, ctx: HogQLParser.CtesContext):
        raise Exception(f"Unsupported node: Ctes")
        # return self.visitChildren(ctx)

    def visitNamedQuery(self, ctx: HogQLParser.NamedQueryContext):
        raise Exception(f"Unsupported node: NamedQuery")
        # return self.visitChildren(ctx)

    def visitColumnAliases(self, ctx: HogQLParser.ColumnAliasesContext):
        raise Exception(f"Unsupported node: ColumnAliases")
        # return self.visitChildren(ctx)

    def visitSelectUnionStmt(self, ctx: HogQLParser.SelectUnionStmtContext):
        raise Exception(f"Unsupported node: SelectUnionStmt")
        # return self.visitChildren(ctx)

    def visitSelectStmtWithParens(self, ctx: HogQLParser.SelectStmtWithParensContext):
        raise Exception(f"Unsupported node: SelectStmtWithParens")
        # return self.visitChildren(ctx)

    def visitSelectStmt(self, ctx: HogQLParser.SelectStmtContext):
        raise Exception(f"Unsupported node: SelectStmt")
        # return self.visitChildren(ctx)

    def visitWithClause(self, ctx: HogQLParser.WithClauseContext):
        raise Exception(f"Unsupported node: WithClause")
        # return self.visitChildren(ctx)

    def visitTopClause(self, ctx: HogQLParser.TopClauseContext):
        raise Exception(f"Unsupported node: TopClause")
        # return self.visitChildren(ctx)

    def visitFromClause(self, ctx: HogQLParser.FromClauseContext):
        raise Exception(f"Unsupported node: FromClause")
        # return self.visitChildren(ctx)

    def visitArrayJoinClause(self, ctx: HogQLParser.ArrayJoinClauseContext):
        raise Exception(f"Unsupported node: ArrayJoinClause")
        # return self.visitChildren(ctx)

    def visitWindowClause(self, ctx: HogQLParser.WindowClauseContext):
        raise Exception(f"Unsupported node: WindowClause")
        # return self.visitChildren(ctx)

    def visitPrewhereClause(self, ctx: HogQLParser.PrewhereClauseContext):
        raise Exception(f"Unsupported node: PrewhereClause")
        # return self.visitChildren(ctx)

    def visitWhereClause(self, ctx: HogQLParser.WhereClauseContext):
        raise Exception(f"Unsupported node: WhereClause")
        # return self.visitChildren(ctx)

    def visitGroupByClause(self, ctx: HogQLParser.GroupByClauseContext):
        raise Exception(f"Unsupported node: GroupByClause")
        # return self.visitChildren(ctx)

    def visitHavingClause(self, ctx: HogQLParser.HavingClauseContext):
        raise Exception(f"Unsupported node: HavingClause")
        # return self.visitChildren(ctx)

    def visitOrderByClause(self, ctx: HogQLParser.OrderByClauseContext):
        raise Exception(f"Unsupported node: OrderByClause")
        # return self.visitChildren(ctx)

    def visitProjectionOrderByClause(self, ctx: HogQLParser.ProjectionOrderByClauseContext):
        raise Exception(f"Unsupported node: ProjectionOrderByClause")
        # return self.visitChildren(ctx)

    def visitLimitByClause(self, ctx: HogQLParser.LimitByClauseContext):
        raise Exception(f"Unsupported node: LimitByClause")
        # return self.visitChildren(ctx)

    def visitLimitClause(self, ctx: HogQLParser.LimitClauseContext):
        raise Exception(f"Unsupported node: LimitClause")
        # return self.visitChildren(ctx)

    def visitSettingsClause(self, ctx: HogQLParser.SettingsClauseContext):
        raise Exception(f"Unsupported node: SettingsClause")
        # return self.visitChildren(ctx)

    def visitJoinExprOp(self, ctx: HogQLParser.JoinExprOpContext):
        raise Exception(f"Unsupported node: JoinExprOp")
        # return self.visitChildren(ctx)

    def visitJoinExprTable(self, ctx: HogQLParser.JoinExprTableContext):
        raise Exception(f"Unsupported node: JoinExprTable")
        # return self.visitChildren(ctx)

    def visitJoinExprParens(self, ctx: HogQLParser.JoinExprParensContext):
        raise Exception(f"Unsupported node: JoinExprParens")
        # return self.visitChildren(ctx)

    def visitJoinExprCrossOp(self, ctx: HogQLParser.JoinExprCrossOpContext):
        raise Exception(f"Unsupported node: JoinExprCrossOp")
        # return self.visitChildren(ctx)

    def visitJoinOpInner(self, ctx: HogQLParser.JoinOpInnerContext):
        raise Exception(f"Unsupported node: JoinOpInner")
        # return self.visitChildren(ctx)

    def visitJoinOpLeftRight(self, ctx: HogQLParser.JoinOpLeftRightContext):
        raise Exception(f"Unsupported node: JoinOpLeftRight")
        # return self.visitChildren(ctx)

    def visitJoinOpFull(self, ctx: HogQLParser.JoinOpFullContext):
        raise Exception(f"Unsupported node: JoinOpFull")
        # return self.visitChildren(ctx)

    def visitJoinOpCross(self, ctx: HogQLParser.JoinOpCrossContext):
        raise Exception(f"Unsupported node: JoinOpCross")
        # return self.visitChildren(ctx)

    def visitJoinConstraintClause(self, ctx: HogQLParser.JoinConstraintClauseContext):
        raise Exception(f"Unsupported node: JoinConstraintClause")
        # return self.visitChildren(ctx)

    def visitSampleClause(self, ctx: HogQLParser.SampleClauseContext):
        raise Exception(f"Unsupported node: SampleClause")
        # return self.visitChildren(ctx)

    def visitLimitExpr(self, ctx: HogQLParser.LimitExprContext):
        raise Exception(f"Unsupported node: LimitExpr")
        # return self.visitChildren(ctx)

    def visitOrderExprList(self, ctx: HogQLParser.OrderExprListContext):
        raise Exception(f"Unsupported node: OrderExprList")
        # return self.visitChildren(ctx)

    def visitOrderExpr(self, ctx: HogQLParser.OrderExprContext):
        raise Exception(f"Unsupported node: OrderExpr")
        # return self.visitChildren(ctx)

    def visitRatioExpr(self, ctx: HogQLParser.RatioExprContext):
        raise Exception(f"Unsupported node: RatioExpr")
        # return self.visitChildren(ctx)

    def visitSettingExprList(self, ctx: HogQLParser.SettingExprListContext):
        raise Exception(f"Unsupported node: SettingExprList")
        # return self.visitChildren(ctx)

    def visitSettingExpr(self, ctx: HogQLParser.SettingExprContext):
        raise Exception(f"Unsupported node: SettingExpr")
        # return self.visitChildren(ctx)

    def visitWindowExpr(self, ctx: HogQLParser.WindowExprContext):
        raise Exception(f"Unsupported node: WindowExpr")
        # return self.visitChildren(ctx)

    def visitWinPartitionByClause(self, ctx: HogQLParser.WinPartitionByClauseContext):
        raise Exception(f"Unsupported node: WinPartitionByClause")
        # return self.visitChildren(ctx)

    def visitWinOrderByClause(self, ctx: HogQLParser.WinOrderByClauseContext):
        raise Exception(f"Unsupported node: WinOrderByClause")
        # return self.visitChildren(ctx)

    def visitWinFrameClause(self, ctx: HogQLParser.WinFrameClauseContext):
        raise Exception(f"Unsupported node: WinFrameClause")
        # return self.visitChildren(ctx)

    def visitFrameStart(self, ctx: HogQLParser.FrameStartContext):
        raise Exception(f"Unsupported node: FrameStart")
        # return self.visitChildren(ctx)

    def visitFrameBetween(self, ctx: HogQLParser.FrameBetweenContext):
        raise Exception(f"Unsupported node: FrameBetween")
        # return self.visitChildren(ctx)

    def visitWinFrameBound(self, ctx: HogQLParser.WinFrameBoundContext):
        raise Exception(f"Unsupported node: WinFrameBound")
        # return self.visitChildren(ctx)

    def visitColumnTypeExprSimple(self, ctx: HogQLParser.ColumnTypeExprSimpleContext):
        raise Exception(f"Unsupported node: ColumnTypeExprSimple")
        # return self.visitChildren(ctx)

    def visitColumnTypeExprNested(self, ctx: HogQLParser.ColumnTypeExprNestedContext):
        raise Exception(f"Unsupported node: ColumnTypeExprNested")
        # return self.visitChildren(ctx)

    def visitColumnTypeExprEnum(self, ctx: HogQLParser.ColumnTypeExprEnumContext):
        raise Exception(f"Unsupported node: ColumnTypeExprEnum")
        # return self.visitChildren(ctx)

    def visitColumnTypeExprComplex(self, ctx: HogQLParser.ColumnTypeExprComplexContext):
        raise Exception(f"Unsupported node: ColumnTypeExprComplex")
        # return self.visitChildren(ctx)

    def visitColumnTypeExprParam(self, ctx: HogQLParser.ColumnTypeExprParamContext):
        raise Exception(f"Unsupported node: ColumnTypeExprParam")
        # return self.visitChildren(ctx)

    def visitColumnExprList(self, ctx: HogQLParser.ColumnExprListContext):
        raise Exception(f"Unsupported node: ColumnExprList")
        # return self.visitChildren(ctx)

    def visitColumnsExprAsterisk(self, ctx: HogQLParser.ColumnsExprAsteriskContext):
        raise Exception(f"Unsupported node: ColumnsExprAsterisk")
        # return self.visitChildren(ctx)

    def visitColumnsExprSubquery(self, ctx: HogQLParser.ColumnsExprSubqueryContext):
        raise Exception(f"Unsupported node: ColumnsExprSubquery")
        # return self.visitChildren(ctx)

    def visitColumnsExprColumn(self, ctx: HogQLParser.ColumnsExprColumnContext):
        raise Exception(f"Unsupported node: ColumnsExprColumn")
        # return self.visitChildren(ctx)

    def visitColumnExprTernaryOp(self, ctx: HogQLParser.ColumnExprTernaryOpContext):
        raise Exception(f"Unsupported node: ColumnExprTernaryOp")
        # return self.visitChildren(ctx)

    def visitColumnExprAlias(self, ctx: HogQLParser.ColumnExprAliasContext):
        raise Exception(f"Unsupported node: ColumnExprAlias")
        # return self.visitChildren(ctx)

    def visitColumnExprExtract(self, ctx: HogQLParser.ColumnExprExtractContext):
        raise Exception(f"Unsupported node: ColumnExprExtract")
        # return self.visitChildren(ctx)

    def visitColumnExprNegate(self, ctx: HogQLParser.ColumnExprNegateContext):
        raise Exception(f"Unsupported node: ColumnExprNegate")
        # return self.visitChildren(ctx)

    def visitColumnExprSubquery(self, ctx: HogQLParser.ColumnExprSubqueryContext):
        raise Exception(f"Unsupported node: ColumnExprSubquery")
        # return self.visitChildren(ctx)

    def visitColumnExprLiteral(self, ctx: HogQLParser.ColumnExprLiteralContext):
        # raise Exception(f"Unsupported node: ColumnExprLiteral")
        return self.visitChildren(ctx)

    def visitColumnExprArray(self, ctx: HogQLParser.ColumnExprArrayContext):
        raise Exception(f"Unsupported node: ColumnExprArray")
        # return self.visitChildren(ctx)

    def visitColumnExprSubstring(self, ctx: HogQLParser.ColumnExprSubstringContext):
        raise Exception(f"Unsupported node: ColumnExprSubstring")
        # return self.visitChildren(ctx)

    def visitColumnExprCast(self, ctx: HogQLParser.ColumnExprCastContext):
        raise Exception(f"Unsupported node: ColumnExprCast")
        # return self.visitChildren(ctx)

    def visitColumnExprOr(self, ctx: HogQLParser.ColumnExprOrContext):
        raise Exception(f"Unsupported node: ColumnExprOr")
        # return self.visitChildren(ctx)

    def visitColumnExprPrecedence1(self, ctx: HogQLParser.ColumnExprPrecedence1Context):
        if ctx.operator.text == "/":
            op = ast.BinaryOperationType.Div
        elif ctx.operator.text == "*":
            op = ast.BinaryOperationType.Mult
        elif ctx.operator.text == "%":
            op = ast.BinaryOperationType.Mod
        else:
            raise Exception(f"Unsupported precedence-1 binary operator: {ctx.operator.text}")
        return ast.BinaryOperation(left=parse_tree_to_expr(ctx.left), right=parse_tree_to_expr(ctx.right), op=op)

    def visitColumnExprPrecedence2(self, ctx: HogQLParser.ColumnExprPrecedence2Context):
        if ctx.operator.text == "+":
            op = ast.BinaryOperationType.Add
        elif ctx.operator.text == "-":
            op = ast.BinaryOperationType.Sub
        else:
            raise Exception(f"Unsupported precedence-2 binary operator: {ctx.operator.text}")
        return ast.BinaryOperation(left=parse_tree_to_expr(ctx.left), right=parse_tree_to_expr(ctx.right), op=op)

    def visitColumnExprPrecedence3(self, ctx: HogQLParser.ColumnExprPrecedence3Context):
        raise Exception(f"Unsupported node: ColumnExprPrecedence3")
        # return self.visitChildren(ctx)

    def visitColumnExprInterval(self, ctx: HogQLParser.ColumnExprIntervalContext):
        raise Exception(f"Unsupported node: ColumnExprInterval")
        # return self.visitChildren(ctx)

    def visitColumnExprIsNull(self, ctx: HogQLParser.ColumnExprIsNullContext):
        raise Exception(f"Unsupported node: ColumnExprIsNull")
        # return self.visitChildren(ctx)

    def visitColumnExprWinFunctionTarget(self, ctx: HogQLParser.ColumnExprWinFunctionTargetContext):
        raise Exception(f"Unsupported node: ColumnExprWinFunctionTarget")
        # return self.visitChildren(ctx)

    def visitColumnExprTrim(self, ctx: HogQLParser.ColumnExprTrimContext):
        raise Exception(f"Unsupported node: ColumnExprTrim")
        # return self.visitChildren(ctx)

    def visitColumnExprTuple(self, ctx: HogQLParser.ColumnExprTupleContext):
        raise Exception(f"Unsupported node: ColumnExprTuple")
        # return self.visitChildren(ctx)

    def visitColumnExprArrayAccess(self, ctx: HogQLParser.ColumnExprArrayAccessContext):
        raise Exception(f"Unsupported node: ColumnExprArrayAccess")
        # return self.visitChildren(ctx)

    def visitColumnExprBetween(self, ctx: HogQLParser.ColumnExprBetweenContext):
        raise Exception(f"Unsupported node: ColumnExprBetween")
        # return self.visitChildren(ctx)

    def visitColumnExprParens(self, ctx: HogQLParser.ColumnExprParensContext):
        raise Exception(f"Unsupported node: ColumnExprParens")
        # return self.visitChildren(ctx)

    def visitColumnExprTimestamp(self, ctx: HogQLParser.ColumnExprTimestampContext):
        raise Exception(f"Unsupported node: ColumnExprTimestamp")
        # return self.visitChildren(ctx)

    def visitColumnExprAnd(self, ctx: HogQLParser.ColumnExprAndContext):
        raise Exception(f"Unsupported node: ColumnExprAnd")
        # return self.visitChildren(ctx)

    def visitColumnExprTupleAccess(self, ctx: HogQLParser.ColumnExprTupleAccessContext):
        raise Exception(f"Unsupported node: ColumnExprTupleAccess")
        # return self.visitChildren(ctx)

    def visitColumnExprCase(self, ctx: HogQLParser.ColumnExprCaseContext):
        raise Exception(f"Unsupported node: ColumnExprCase")
        # return self.visitChildren(ctx)

    def visitColumnExprDate(self, ctx: HogQLParser.ColumnExprDateContext):
        raise Exception(f"Unsupported node: ColumnExprDate")
        # return self.visitChildren(ctx)

    def visitColumnExprNot(self, ctx: HogQLParser.ColumnExprNotContext):
        raise Exception(f"Unsupported node: ColumnExprNot")
        # return self.visitChildren(ctx)

    def visitColumnExprWinFunction(self, ctx: HogQLParser.ColumnExprWinFunctionContext):
        raise Exception(f"Unsupported node: ColumnExprWinFunction")
        # return self.visitChildren(ctx)

    def visitColumnExprIdentifier(self, ctx: HogQLParser.ColumnExprIdentifierContext):
        raise Exception(f"Unsupported node: ColumnExprIdentifier")
        # return self.visitChildren(ctx)

    def visitColumnExprFunction(self, ctx: HogQLParser.ColumnExprFunctionContext):
        raise Exception(f"Unsupported node: ColumnExprFunction")
        # return self.visitChildren(ctx)

    def visitColumnExprAsterisk(self, ctx: HogQLParser.ColumnExprAsteriskContext):
        raise Exception(f"Unsupported node: ColumnExprAsterisk")
        # return self.visitChildren(ctx)

    def visitColumnArgList(self, ctx: HogQLParser.ColumnArgListContext):
        raise Exception(f"Unsupported node: ColumnArgList")
        # return self.visitChildren(ctx)

    def visitColumnArgExpr(self, ctx: HogQLParser.ColumnArgExprContext):
        raise Exception(f"Unsupported node: ColumnArgExpr")
        # return self.visitChildren(ctx)

    def visitColumnLambdaExpr(self, ctx: HogQLParser.ColumnLambdaExprContext):
        raise Exception(f"Unsupported node: ColumnLambdaExpr")
        # return self.visitChildren(ctx)

    def visitColumnIdentifier(self, ctx: HogQLParser.ColumnIdentifierContext):
        raise Exception(f"Unsupported node: ColumnIdentifier")
        # return self.visitChildren(ctx)

    def visitNestedIdentifier(self, ctx: HogQLParser.NestedIdentifierContext):
        raise Exception(f"Unsupported node: NestedIdentifier")
        # return self.visitChildren(ctx)

    def visitTableExprIdentifier(self, ctx: HogQLParser.TableExprIdentifierContext):
        raise Exception(f"Unsupported node: TableExprIdentifier")
        # return self.visitChildren(ctx)

    def visitTableExprSubquery(self, ctx: HogQLParser.TableExprSubqueryContext):
        raise Exception(f"Unsupported node: TableExprSubquery")
        # return self.visitChildren(ctx)

    def visitTableExprAlias(self, ctx: HogQLParser.TableExprAliasContext):
        raise Exception(f"Unsupported node: TableExprAlias")
        # return self.visitChildren(ctx)

    def visitTableExprFunction(self, ctx: HogQLParser.TableExprFunctionContext):
        raise Exception(f"Unsupported node: TableExprFunction")
        # return self.visitChildren(ctx)

    def visitTableFunctionExpr(self, ctx: HogQLParser.TableFunctionExprContext):
        raise Exception(f"Unsupported node: TableFunctionExpr")
        # return self.visitChildren(ctx)

    def visitTableIdentifier(self, ctx: HogQLParser.TableIdentifierContext):
        raise Exception(f"Unsupported node: TableIdentifier")
        # return self.visitChildren(ctx)

    def visitTableArgList(self, ctx: HogQLParser.TableArgListContext):
        raise Exception(f"Unsupported node: TableArgList")
        # return self.visitChildren(ctx)

    def visitTableArgExpr(self, ctx: HogQLParser.TableArgExprContext):
        raise Exception(f"Unsupported node: TableArgExpr")
        # return self.visitChildren(ctx)

    def visitDatabaseIdentifier(self, ctx: HogQLParser.DatabaseIdentifierContext):
        raise Exception(f"Unsupported node: DatabaseIdentifier")
        # return self.visitChildren(ctx)

    def visitFloatingLiteral(self, ctx: HogQLParser.FloatingLiteralContext):
        return ast.Constant(value=float(ctx.getText()))

    def visitNumberLiteral(self, ctx: HogQLParser.NumberLiteralContext):
        return ast.Constant(value=int(ctx.getText()))

    def visitLiteral(self, ctx: HogQLParser.LiteralContext):
        return self.visitChildren(ctx)

    def visitInterval(self, ctx: HogQLParser.IntervalContext):
        raise Exception(f"Unsupported node: Interval")
        # return self.visitChildren(ctx)

    def visitKeyword(self, ctx: HogQLParser.KeywordContext):
        raise Exception(f"Unsupported node: Keyword")
        # return self.visitChildren(ctx)

    def visitKeywordForAlias(self, ctx: HogQLParser.KeywordForAliasContext):
        raise Exception(f"Unsupported node: KeywordForAlias")
        # return self.visitChildren(ctx)

    def visitAlias(self, ctx: HogQLParser.AliasContext):
        raise Exception(f"Unsupported node: Alias")
        # return self.visitChildren(ctx)

    def visitIdentifier(self, ctx: HogQLParser.IdentifierContext):
        raise Exception(f"Unsupported node: Identifier")
        # return self.visitChildren(ctx)

    def visitIdentifierOrNull(self, ctx: HogQLParser.IdentifierOrNullContext):
        raise Exception(f"Unsupported node: IdentifierOrNull")
        # return self.visitChildren(ctx)

    def visitEnumValue(self, ctx: HogQLParser.EnumValueContext):
        raise Exception(f"Unsupported node: EnumValue")
        # return self.visitChildren(ctx)
