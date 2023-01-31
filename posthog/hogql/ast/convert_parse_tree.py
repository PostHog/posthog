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

    # Visit a parse tree produced by HogQLParser#queryStmt.
    def visitQueryStmt(self, ctx: HogQLParser.QueryStmtContext):
        raise Exception(f"Unsupported node: QueryStmt")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#query.
    def visitQuery(self, ctx: HogQLParser.QueryContext):
        raise Exception(f"Unsupported node: Query")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#ctes.
    def visitCtes(self, ctx: HogQLParser.CtesContext):
        raise Exception(f"Unsupported node: Ctes")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#namedQuery.
    def visitNamedQuery(self, ctx: HogQLParser.NamedQueryContext):
        raise Exception(f"Unsupported node: NamedQuery")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#columnAliases.
    def visitColumnAliases(self, ctx: HogQLParser.ColumnAliasesContext):
        raise Exception(f"Unsupported node: ColumnAliases")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#selectUnionStmt.
    def visitSelectUnionStmt(self, ctx: HogQLParser.SelectUnionStmtContext):
        raise Exception(f"Unsupported node: SelectUnionStmt")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#selectStmtWithParens.
    def visitSelectStmtWithParens(self, ctx: HogQLParser.SelectStmtWithParensContext):
        raise Exception(f"Unsupported node: SelectStmtWithParens")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#selectStmt.
    def visitSelectStmt(self, ctx: HogQLParser.SelectStmtContext):
        raise Exception(f"Unsupported node: SelectStmt")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#withClause.
    def visitWithClause(self, ctx: HogQLParser.WithClauseContext):
        raise Exception(f"Unsupported node: WithClause")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#topClause.
    def visitTopClause(self, ctx: HogQLParser.TopClauseContext):
        raise Exception(f"Unsupported node: TopClause")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#fromClause.
    def visitFromClause(self, ctx: HogQLParser.FromClauseContext):
        raise Exception(f"Unsupported node: FromClause")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#arrayJoinClause.
    def visitArrayJoinClause(self, ctx: HogQLParser.ArrayJoinClauseContext):
        raise Exception(f"Unsupported node: ArrayJoinClause")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#windowClause.
    def visitWindowClause(self, ctx: HogQLParser.WindowClauseContext):
        raise Exception(f"Unsupported node: WindowClause")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#prewhereClause.
    def visitPrewhereClause(self, ctx: HogQLParser.PrewhereClauseContext):
        raise Exception(f"Unsupported node: PrewhereClause")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#whereClause.
    def visitWhereClause(self, ctx: HogQLParser.WhereClauseContext):
        raise Exception(f"Unsupported node: WhereClause")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#groupByClause.
    def visitGroupByClause(self, ctx: HogQLParser.GroupByClauseContext):
        raise Exception(f"Unsupported node: GroupByClause")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#havingClause.
    def visitHavingClause(self, ctx: HogQLParser.HavingClauseContext):
        raise Exception(f"Unsupported node: HavingClause")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#orderByClause.
    def visitOrderByClause(self, ctx: HogQLParser.OrderByClauseContext):
        raise Exception(f"Unsupported node: OrderByClause")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#projectionOrderByClause.
    def visitProjectionOrderByClause(self, ctx: HogQLParser.ProjectionOrderByClauseContext):
        raise Exception(f"Unsupported node: ProjectionOrderByClause")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#limitByClause.
    def visitLimitByClause(self, ctx: HogQLParser.LimitByClauseContext):
        raise Exception(f"Unsupported node: LimitByClause")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#limitClause.
    def visitLimitClause(self, ctx: HogQLParser.LimitClauseContext):
        raise Exception(f"Unsupported node: LimitClause")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#settingsClause.
    def visitSettingsClause(self, ctx: HogQLParser.SettingsClauseContext):
        raise Exception(f"Unsupported node: SettingsClause")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#JoinExprOp.
    def visitJoinExprOp(self, ctx: HogQLParser.JoinExprOpContext):
        raise Exception(f"Unsupported node: JoinExprOp")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#JoinExprTable.
    def visitJoinExprTable(self, ctx: HogQLParser.JoinExprTableContext):
        raise Exception(f"Unsupported node: JoinExprTable")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#JoinExprParens.
    def visitJoinExprParens(self, ctx: HogQLParser.JoinExprParensContext):
        raise Exception(f"Unsupported node: JoinExprParens")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#JoinExprCrossOp.
    def visitJoinExprCrossOp(self, ctx: HogQLParser.JoinExprCrossOpContext):
        raise Exception(f"Unsupported node: JoinExprCrossOp")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#JoinOpInner.
    def visitJoinOpInner(self, ctx: HogQLParser.JoinOpInnerContext):
        raise Exception(f"Unsupported node: JoinOpInner")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#JoinOpLeftRight.
    def visitJoinOpLeftRight(self, ctx: HogQLParser.JoinOpLeftRightContext):
        raise Exception(f"Unsupported node: JoinOpLeftRight")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#JoinOpFull.
    def visitJoinOpFull(self, ctx: HogQLParser.JoinOpFullContext):
        raise Exception(f"Unsupported node: JoinOpFull")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#joinOpCross.
    def visitJoinOpCross(self, ctx: HogQLParser.JoinOpCrossContext):
        raise Exception(f"Unsupported node: JoinOpCross")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#joinConstraintClause.
    def visitJoinConstraintClause(self, ctx: HogQLParser.JoinConstraintClauseContext):
        raise Exception(f"Unsupported node: JoinConstraintClause")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#sampleClause.
    def visitSampleClause(self, ctx: HogQLParser.SampleClauseContext):
        raise Exception(f"Unsupported node: SampleClause")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#limitExpr.
    def visitLimitExpr(self, ctx: HogQLParser.LimitExprContext):
        raise Exception(f"Unsupported node: LimitExpr")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#orderExprList.
    def visitOrderExprList(self, ctx: HogQLParser.OrderExprListContext):
        raise Exception(f"Unsupported node: OrderExprList")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#orderExpr.
    def visitOrderExpr(self, ctx: HogQLParser.OrderExprContext):
        raise Exception(f"Unsupported node: OrderExpr")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#ratioExpr.
    def visitRatioExpr(self, ctx: HogQLParser.RatioExprContext):
        raise Exception(f"Unsupported node: RatioExpr")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#settingExprList.
    def visitSettingExprList(self, ctx: HogQLParser.SettingExprListContext):
        raise Exception(f"Unsupported node: SettingExprList")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#settingExpr.
    def visitSettingExpr(self, ctx: HogQLParser.SettingExprContext):
        raise Exception(f"Unsupported node: SettingExpr")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#windowExpr.
    def visitWindowExpr(self, ctx: HogQLParser.WindowExprContext):
        raise Exception(f"Unsupported node: WindowExpr")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#winPartitionByClause.
    def visitWinPartitionByClause(self, ctx: HogQLParser.WinPartitionByClauseContext):
        raise Exception(f"Unsupported node: WinPartitionByClause")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#winOrderByClause.
    def visitWinOrderByClause(self, ctx: HogQLParser.WinOrderByClauseContext):
        raise Exception(f"Unsupported node: WinOrderByClause")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#winFrameClause.
    def visitWinFrameClause(self, ctx: HogQLParser.WinFrameClauseContext):
        raise Exception(f"Unsupported node: WinFrameClause")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#frameStart.
    def visitFrameStart(self, ctx: HogQLParser.FrameStartContext):
        raise Exception(f"Unsupported node: FrameStart")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#frameBetween.
    def visitFrameBetween(self, ctx: HogQLParser.FrameBetweenContext):
        raise Exception(f"Unsupported node: FrameBetween")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#winFrameBound.
    def visitWinFrameBound(self, ctx: HogQLParser.WinFrameBoundContext):
        raise Exception(f"Unsupported node: WinFrameBound")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#ColumnTypeExprSimple.
    def visitColumnTypeExprSimple(self, ctx: HogQLParser.ColumnTypeExprSimpleContext):
        raise Exception(f"Unsupported node: ColumnTypeExprSimple")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#ColumnTypeExprNested.
    def visitColumnTypeExprNested(self, ctx: HogQLParser.ColumnTypeExprNestedContext):
        raise Exception(f"Unsupported node: ColumnTypeExprNested")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#ColumnTypeExprEnum.
    def visitColumnTypeExprEnum(self, ctx: HogQLParser.ColumnTypeExprEnumContext):
        raise Exception(f"Unsupported node: ColumnTypeExprEnum")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#ColumnTypeExprComplex.
    def visitColumnTypeExprComplex(self, ctx: HogQLParser.ColumnTypeExprComplexContext):
        raise Exception(f"Unsupported node: ColumnTypeExprComplex")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#ColumnTypeExprParam.
    def visitColumnTypeExprParam(self, ctx: HogQLParser.ColumnTypeExprParamContext):
        raise Exception(f"Unsupported node: ColumnTypeExprParam")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#columnExprList.
    def visitColumnExprList(self, ctx: HogQLParser.ColumnExprListContext):
        raise Exception(f"Unsupported node: ColumnExprList")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#ColumnsExprAsterisk.
    def visitColumnsExprAsterisk(self, ctx: HogQLParser.ColumnsExprAsteriskContext):
        raise Exception(f"Unsupported node: ColumnsExprAsterisk")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#ColumnsExprSubquery.
    def visitColumnsExprSubquery(self, ctx: HogQLParser.ColumnsExprSubqueryContext):
        raise Exception(f"Unsupported node: ColumnsExprSubquery")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#ColumnsExprColumn.
    def visitColumnsExprColumn(self, ctx: HogQLParser.ColumnsExprColumnContext):
        raise Exception(f"Unsupported node: ColumnsExprColumn")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#ColumnExprTernaryOp.
    def visitColumnExprTernaryOp(self, ctx: HogQLParser.ColumnExprTernaryOpContext):
        raise Exception(f"Unsupported node: ColumnExprTernaryOp")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#ColumnExprAlias.
    def visitColumnExprAlias(self, ctx: HogQLParser.ColumnExprAliasContext):
        raise Exception(f"Unsupported node: ColumnExprAlias")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#ColumnExprExtract.
    def visitColumnExprExtract(self, ctx: HogQLParser.ColumnExprExtractContext):
        raise Exception(f"Unsupported node: ColumnExprExtract")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#ColumnExprNegate.
    def visitColumnExprNegate(self, ctx: HogQLParser.ColumnExprNegateContext):
        raise Exception(f"Unsupported node: ColumnExprNegate")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#ColumnExprSubquery.
    def visitColumnExprSubquery(self, ctx: HogQLParser.ColumnExprSubqueryContext):
        raise Exception(f"Unsupported node: ColumnExprSubquery")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#ColumnExprLiteral.
    def visitColumnExprLiteral(self, ctx: HogQLParser.ColumnExprLiteralContext):
        # raise Exception(f"Unsupported node: ColumnExprLiteral")
        return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#ColumnExprArray.
    def visitColumnExprArray(self, ctx: HogQLParser.ColumnExprArrayContext):
        raise Exception(f"Unsupported node: ColumnExprArray")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#ColumnExprSubstring.
    def visitColumnExprSubstring(self, ctx: HogQLParser.ColumnExprSubstringContext):
        raise Exception(f"Unsupported node: ColumnExprSubstring")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#ColumnExprCast.
    def visitColumnExprCast(self, ctx: HogQLParser.ColumnExprCastContext):
        raise Exception(f"Unsupported node: ColumnExprCast")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#ColumnExprOr.
    def visitColumnExprOr(self, ctx: HogQLParser.ColumnExprOrContext):
        raise Exception(f"Unsupported node: ColumnExprOr")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#ColumnExprPrecedence1.
    def visitColumnExprPrecedence1(self, ctx: HogQLParser.ColumnExprPrecedence1Context):
        raise Exception(f"Unsupported node: ColumnExprPrecedence1")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#ColumnExprPrecedence2.
    def visitColumnExprPrecedence2(self, ctx: HogQLParser.ColumnExprPrecedence2Context):
        if ctx.operator.text == "+":
            op = ast.BinaryOperationType.Add
        elif ctx.operator.text == "-":
            op = ast.BinaryOperationType.Sub
        else:
            raise Exception(f"Unsupported precedence-2 binary operator: {ctx.operator.text}")

        return ast.BinaryOperation(left=parse_tree_to_expr(ctx.left), right=parse_tree_to_expr(ctx.right), op=op)

    # Visit a parse tree produced by HogQLParser#ColumnExprPrecedence3.
    def visitColumnExprPrecedence3(self, ctx: HogQLParser.ColumnExprPrecedence3Context):
        raise Exception(f"Unsupported node: ColumnExprPrecedence3")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#ColumnExprInterval.
    def visitColumnExprInterval(self, ctx: HogQLParser.ColumnExprIntervalContext):
        raise Exception(f"Unsupported node: ColumnExprInterval")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#ColumnExprIsNull.
    def visitColumnExprIsNull(self, ctx: HogQLParser.ColumnExprIsNullContext):
        raise Exception(f"Unsupported node: ColumnExprIsNull")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#ColumnExprWinFunctionTarget.
    def visitColumnExprWinFunctionTarget(self, ctx: HogQLParser.ColumnExprWinFunctionTargetContext):
        raise Exception(f"Unsupported node: ColumnExprWinFunctionTarget")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#ColumnExprTrim.
    def visitColumnExprTrim(self, ctx: HogQLParser.ColumnExprTrimContext):
        raise Exception(f"Unsupported node: ColumnExprTrim")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#ColumnExprTuple.
    def visitColumnExprTuple(self, ctx: HogQLParser.ColumnExprTupleContext):
        raise Exception(f"Unsupported node: ColumnExprTuple")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#ColumnExprArrayAccess.
    def visitColumnExprArrayAccess(self, ctx: HogQLParser.ColumnExprArrayAccessContext):
        raise Exception(f"Unsupported node: ColumnExprArrayAccess")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#ColumnExprBetween.
    def visitColumnExprBetween(self, ctx: HogQLParser.ColumnExprBetweenContext):
        raise Exception(f"Unsupported node: ColumnExprBetween")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#ColumnExprParens.
    def visitColumnExprParens(self, ctx: HogQLParser.ColumnExprParensContext):
        raise Exception(f"Unsupported node: ColumnExprParens")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#ColumnExprTimestamp.
    def visitColumnExprTimestamp(self, ctx: HogQLParser.ColumnExprTimestampContext):
        raise Exception(f"Unsupported node: ColumnExprTimestamp")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#ColumnExprAnd.
    def visitColumnExprAnd(self, ctx: HogQLParser.ColumnExprAndContext):
        raise Exception(f"Unsupported node: ColumnExprAnd")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#ColumnExprTupleAccess.
    def visitColumnExprTupleAccess(self, ctx: HogQLParser.ColumnExprTupleAccessContext):
        raise Exception(f"Unsupported node: ColumnExprTupleAccess")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#ColumnExprCase.
    def visitColumnExprCase(self, ctx: HogQLParser.ColumnExprCaseContext):
        raise Exception(f"Unsupported node: ColumnExprCase")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#ColumnExprDate.
    def visitColumnExprDate(self, ctx: HogQLParser.ColumnExprDateContext):
        raise Exception(f"Unsupported node: ColumnExprDate")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#ColumnExprNot.
    def visitColumnExprNot(self, ctx: HogQLParser.ColumnExprNotContext):
        raise Exception(f"Unsupported node: ColumnExprNot")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#ColumnExprWinFunction.
    def visitColumnExprWinFunction(self, ctx: HogQLParser.ColumnExprWinFunctionContext):
        raise Exception(f"Unsupported node: ColumnExprWinFunction")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#ColumnExprIdentifier.
    def visitColumnExprIdentifier(self, ctx: HogQLParser.ColumnExprIdentifierContext):
        raise Exception(f"Unsupported node: ColumnExprIdentifier")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#ColumnExprFunction.
    def visitColumnExprFunction(self, ctx: HogQLParser.ColumnExprFunctionContext):
        raise Exception(f"Unsupported node: ColumnExprFunction")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#ColumnExprAsterisk.
    def visitColumnExprAsterisk(self, ctx: HogQLParser.ColumnExprAsteriskContext):
        raise Exception(f"Unsupported node: ColumnExprAsterisk")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#columnArgList.
    def visitColumnArgList(self, ctx: HogQLParser.ColumnArgListContext):
        raise Exception(f"Unsupported node: ColumnArgList")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#columnArgExpr.
    def visitColumnArgExpr(self, ctx: HogQLParser.ColumnArgExprContext):
        raise Exception(f"Unsupported node: ColumnArgExpr")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#columnLambdaExpr.
    def visitColumnLambdaExpr(self, ctx: HogQLParser.ColumnLambdaExprContext):
        raise Exception(f"Unsupported node: ColumnLambdaExpr")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#columnIdentifier.
    def visitColumnIdentifier(self, ctx: HogQLParser.ColumnIdentifierContext):
        raise Exception(f"Unsupported node: ColumnIdentifier")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#nestedIdentifier.
    def visitNestedIdentifier(self, ctx: HogQLParser.NestedIdentifierContext):
        raise Exception(f"Unsupported node: NestedIdentifier")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#TableExprIdentifier.
    def visitTableExprIdentifier(self, ctx: HogQLParser.TableExprIdentifierContext):
        raise Exception(f"Unsupported node: TableExprIdentifier")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#TableExprSubquery.
    def visitTableExprSubquery(self, ctx: HogQLParser.TableExprSubqueryContext):
        raise Exception(f"Unsupported node: TableExprSubquery")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#TableExprAlias.
    def visitTableExprAlias(self, ctx: HogQLParser.TableExprAliasContext):
        raise Exception(f"Unsupported node: TableExprAlias")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#TableExprFunction.
    def visitTableExprFunction(self, ctx: HogQLParser.TableExprFunctionContext):
        raise Exception(f"Unsupported node: TableExprFunction")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#tableFunctionExpr.
    def visitTableFunctionExpr(self, ctx: HogQLParser.TableFunctionExprContext):
        raise Exception(f"Unsupported node: TableFunctionExpr")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#tableIdentifier.
    def visitTableIdentifier(self, ctx: HogQLParser.TableIdentifierContext):
        raise Exception(f"Unsupported node: TableIdentifier")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#tableArgList.
    def visitTableArgList(self, ctx: HogQLParser.TableArgListContext):
        raise Exception(f"Unsupported node: TableArgList")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#tableArgExpr.
    def visitTableArgExpr(self, ctx: HogQLParser.TableArgExprContext):
        raise Exception(f"Unsupported node: TableArgExpr")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#databaseIdentifier.
    def visitDatabaseIdentifier(self, ctx: HogQLParser.DatabaseIdentifierContext):
        raise Exception(f"Unsupported node: DatabaseIdentifier")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#floatingLiteral.
    def visitFloatingLiteral(self, ctx: HogQLParser.FloatingLiteralContext):
        return ast.Constant(value=float(ctx.getText()))

    # Visit a parse tree produced by HogQLParser#numberLiteral.
    def visitNumberLiteral(self, ctx: HogQLParser.NumberLiteralContext):
        return ast.Constant(value=int(ctx.getText()))

    # Visit a parse tree produced by HogQLParser#literal.
    def visitLiteral(self, ctx: HogQLParser.LiteralContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#interval.
    def visitInterval(self, ctx: HogQLParser.IntervalContext):
        raise Exception(f"Unsupported node: Interval")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#keyword.
    def visitKeyword(self, ctx: HogQLParser.KeywordContext):
        raise Exception(f"Unsupported node: Keyword")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#keywordForAlias.
    def visitKeywordForAlias(self, ctx: HogQLParser.KeywordForAliasContext):
        raise Exception(f"Unsupported node: KeywordForAlias")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#alias.
    def visitAlias(self, ctx: HogQLParser.AliasContext):
        raise Exception(f"Unsupported node: Alias")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#identifier.
    def visitIdentifier(self, ctx: HogQLParser.IdentifierContext):
        raise Exception(f"Unsupported node: Identifier")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#identifierOrNull.
    def visitIdentifierOrNull(self, ctx: HogQLParser.IdentifierOrNullContext):
        raise Exception(f"Unsupported node: IdentifierOrNull")
        # return self.visitChildren(ctx)

    # Visit a parse tree produced by HogQLParser#enumValue.
    def visitEnumValue(self, ctx: HogQLParser.EnumValueContext):
        raise Exception(f"Unsupported node: EnumValue")
        # return self.visitChildren(ctx)
