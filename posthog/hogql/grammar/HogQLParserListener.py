# Generated from HogQLParser.g4 by ANTLR 4.11.1
from antlr4 import *

if __name__ is not None and "." in __name__:
    from .HogQLParser import HogQLParser
else:
    from HogQLParser import HogQLParser

# This class defines a complete listener for a parse tree produced by HogQLParser.
class HogQLParserListener(ParseTreeListener):

    # Enter a parse tree produced by HogQLParser#queryStmt.
    def enterQueryStmt(self, ctx: HogQLParser.QueryStmtContext):
        pass

    # Exit a parse tree produced by HogQLParser#queryStmt.
    def exitQueryStmt(self, ctx: HogQLParser.QueryStmtContext):
        pass

    # Enter a parse tree produced by HogQLParser#query.
    def enterQuery(self, ctx: HogQLParser.QueryContext):
        pass

    # Exit a parse tree produced by HogQLParser#query.
    def exitQuery(self, ctx: HogQLParser.QueryContext):
        pass

    # Enter a parse tree produced by HogQLParser#ctes.
    def enterCtes(self, ctx: HogQLParser.CtesContext):
        pass

    # Exit a parse tree produced by HogQLParser#ctes.
    def exitCtes(self, ctx: HogQLParser.CtesContext):
        pass

    # Enter a parse tree produced by HogQLParser#namedQuery.
    def enterNamedQuery(self, ctx: HogQLParser.NamedQueryContext):
        pass

    # Exit a parse tree produced by HogQLParser#namedQuery.
    def exitNamedQuery(self, ctx: HogQLParser.NamedQueryContext):
        pass

    # Enter a parse tree produced by HogQLParser#columnAliases.
    def enterColumnAliases(self, ctx: HogQLParser.ColumnAliasesContext):
        pass

    # Exit a parse tree produced by HogQLParser#columnAliases.
    def exitColumnAliases(self, ctx: HogQLParser.ColumnAliasesContext):
        pass

    # Enter a parse tree produced by HogQLParser#selectUnionStmt.
    def enterSelectUnionStmt(self, ctx: HogQLParser.SelectUnionStmtContext):
        pass

    # Exit a parse tree produced by HogQLParser#selectUnionStmt.
    def exitSelectUnionStmt(self, ctx: HogQLParser.SelectUnionStmtContext):
        pass

    # Enter a parse tree produced by HogQLParser#selectStmtWithParens.
    def enterSelectStmtWithParens(self, ctx: HogQLParser.SelectStmtWithParensContext):
        pass

    # Exit a parse tree produced by HogQLParser#selectStmtWithParens.
    def exitSelectStmtWithParens(self, ctx: HogQLParser.SelectStmtWithParensContext):
        pass

    # Enter a parse tree produced by HogQLParser#selectStmt.
    def enterSelectStmt(self, ctx: HogQLParser.SelectStmtContext):
        pass

    # Exit a parse tree produced by HogQLParser#selectStmt.
    def exitSelectStmt(self, ctx: HogQLParser.SelectStmtContext):
        pass

    # Enter a parse tree produced by HogQLParser#withClause.
    def enterWithClause(self, ctx: HogQLParser.WithClauseContext):
        pass

    # Exit a parse tree produced by HogQLParser#withClause.
    def exitWithClause(self, ctx: HogQLParser.WithClauseContext):
        pass

    # Enter a parse tree produced by HogQLParser#topClause.
    def enterTopClause(self, ctx: HogQLParser.TopClauseContext):
        pass

    # Exit a parse tree produced by HogQLParser#topClause.
    def exitTopClause(self, ctx: HogQLParser.TopClauseContext):
        pass

    # Enter a parse tree produced by HogQLParser#fromClause.
    def enterFromClause(self, ctx: HogQLParser.FromClauseContext):
        pass

    # Exit a parse tree produced by HogQLParser#fromClause.
    def exitFromClause(self, ctx: HogQLParser.FromClauseContext):
        pass

    # Enter a parse tree produced by HogQLParser#arrayJoinClause.
    def enterArrayJoinClause(self, ctx: HogQLParser.ArrayJoinClauseContext):
        pass

    # Exit a parse tree produced by HogQLParser#arrayJoinClause.
    def exitArrayJoinClause(self, ctx: HogQLParser.ArrayJoinClauseContext):
        pass

    # Enter a parse tree produced by HogQLParser#windowClause.
    def enterWindowClause(self, ctx: HogQLParser.WindowClauseContext):
        pass

    # Exit a parse tree produced by HogQLParser#windowClause.
    def exitWindowClause(self, ctx: HogQLParser.WindowClauseContext):
        pass

    # Enter a parse tree produced by HogQLParser#prewhereClause.
    def enterPrewhereClause(self, ctx: HogQLParser.PrewhereClauseContext):
        pass

    # Exit a parse tree produced by HogQLParser#prewhereClause.
    def exitPrewhereClause(self, ctx: HogQLParser.PrewhereClauseContext):
        pass

    # Enter a parse tree produced by HogQLParser#whereClause.
    def enterWhereClause(self, ctx: HogQLParser.WhereClauseContext):
        pass

    # Exit a parse tree produced by HogQLParser#whereClause.
    def exitWhereClause(self, ctx: HogQLParser.WhereClauseContext):
        pass

    # Enter a parse tree produced by HogQLParser#groupByClause.
    def enterGroupByClause(self, ctx: HogQLParser.GroupByClauseContext):
        pass

    # Exit a parse tree produced by HogQLParser#groupByClause.
    def exitGroupByClause(self, ctx: HogQLParser.GroupByClauseContext):
        pass

    # Enter a parse tree produced by HogQLParser#havingClause.
    def enterHavingClause(self, ctx: HogQLParser.HavingClauseContext):
        pass

    # Exit a parse tree produced by HogQLParser#havingClause.
    def exitHavingClause(self, ctx: HogQLParser.HavingClauseContext):
        pass

    # Enter a parse tree produced by HogQLParser#orderByClause.
    def enterOrderByClause(self, ctx: HogQLParser.OrderByClauseContext):
        pass

    # Exit a parse tree produced by HogQLParser#orderByClause.
    def exitOrderByClause(self, ctx: HogQLParser.OrderByClauseContext):
        pass

    # Enter a parse tree produced by HogQLParser#projectionOrderByClause.
    def enterProjectionOrderByClause(self, ctx: HogQLParser.ProjectionOrderByClauseContext):
        pass

    # Exit a parse tree produced by HogQLParser#projectionOrderByClause.
    def exitProjectionOrderByClause(self, ctx: HogQLParser.ProjectionOrderByClauseContext):
        pass

    # Enter a parse tree produced by HogQLParser#limitByClause.
    def enterLimitByClause(self, ctx: HogQLParser.LimitByClauseContext):
        pass

    # Exit a parse tree produced by HogQLParser#limitByClause.
    def exitLimitByClause(self, ctx: HogQLParser.LimitByClauseContext):
        pass

    # Enter a parse tree produced by HogQLParser#limitClause.
    def enterLimitClause(self, ctx: HogQLParser.LimitClauseContext):
        pass

    # Exit a parse tree produced by HogQLParser#limitClause.
    def exitLimitClause(self, ctx: HogQLParser.LimitClauseContext):
        pass

    # Enter a parse tree produced by HogQLParser#settingsClause.
    def enterSettingsClause(self, ctx: HogQLParser.SettingsClauseContext):
        pass

    # Exit a parse tree produced by HogQLParser#settingsClause.
    def exitSettingsClause(self, ctx: HogQLParser.SettingsClauseContext):
        pass

    # Enter a parse tree produced by HogQLParser#JoinExprOp.
    def enterJoinExprOp(self, ctx: HogQLParser.JoinExprOpContext):
        pass

    # Exit a parse tree produced by HogQLParser#JoinExprOp.
    def exitJoinExprOp(self, ctx: HogQLParser.JoinExprOpContext):
        pass

    # Enter a parse tree produced by HogQLParser#JoinExprTable.
    def enterJoinExprTable(self, ctx: HogQLParser.JoinExprTableContext):
        pass

    # Exit a parse tree produced by HogQLParser#JoinExprTable.
    def exitJoinExprTable(self, ctx: HogQLParser.JoinExprTableContext):
        pass

    # Enter a parse tree produced by HogQLParser#JoinExprParens.
    def enterJoinExprParens(self, ctx: HogQLParser.JoinExprParensContext):
        pass

    # Exit a parse tree produced by HogQLParser#JoinExprParens.
    def exitJoinExprParens(self, ctx: HogQLParser.JoinExprParensContext):
        pass

    # Enter a parse tree produced by HogQLParser#JoinExprCrossOp.
    def enterJoinExprCrossOp(self, ctx: HogQLParser.JoinExprCrossOpContext):
        pass

    # Exit a parse tree produced by HogQLParser#JoinExprCrossOp.
    def exitJoinExprCrossOp(self, ctx: HogQLParser.JoinExprCrossOpContext):
        pass

    # Enter a parse tree produced by HogQLParser#JoinOpInner.
    def enterJoinOpInner(self, ctx: HogQLParser.JoinOpInnerContext):
        pass

    # Exit a parse tree produced by HogQLParser#JoinOpInner.
    def exitJoinOpInner(self, ctx: HogQLParser.JoinOpInnerContext):
        pass

    # Enter a parse tree produced by HogQLParser#JoinOpLeftRight.
    def enterJoinOpLeftRight(self, ctx: HogQLParser.JoinOpLeftRightContext):
        pass

    # Exit a parse tree produced by HogQLParser#JoinOpLeftRight.
    def exitJoinOpLeftRight(self, ctx: HogQLParser.JoinOpLeftRightContext):
        pass

    # Enter a parse tree produced by HogQLParser#JoinOpFull.
    def enterJoinOpFull(self, ctx: HogQLParser.JoinOpFullContext):
        pass

    # Exit a parse tree produced by HogQLParser#JoinOpFull.
    def exitJoinOpFull(self, ctx: HogQLParser.JoinOpFullContext):
        pass

    # Enter a parse tree produced by HogQLParser#joinOpCross.
    def enterJoinOpCross(self, ctx: HogQLParser.JoinOpCrossContext):
        pass

    # Exit a parse tree produced by HogQLParser#joinOpCross.
    def exitJoinOpCross(self, ctx: HogQLParser.JoinOpCrossContext):
        pass

    # Enter a parse tree produced by HogQLParser#joinConstraintClause.
    def enterJoinConstraintClause(self, ctx: HogQLParser.JoinConstraintClauseContext):
        pass

    # Exit a parse tree produced by HogQLParser#joinConstraintClause.
    def exitJoinConstraintClause(self, ctx: HogQLParser.JoinConstraintClauseContext):
        pass

    # Enter a parse tree produced by HogQLParser#sampleClause.
    def enterSampleClause(self, ctx: HogQLParser.SampleClauseContext):
        pass

    # Exit a parse tree produced by HogQLParser#sampleClause.
    def exitSampleClause(self, ctx: HogQLParser.SampleClauseContext):
        pass

    # Enter a parse tree produced by HogQLParser#limitExpr.
    def enterLimitExpr(self, ctx: HogQLParser.LimitExprContext):
        pass

    # Exit a parse tree produced by HogQLParser#limitExpr.
    def exitLimitExpr(self, ctx: HogQLParser.LimitExprContext):
        pass

    # Enter a parse tree produced by HogQLParser#orderExprList.
    def enterOrderExprList(self, ctx: HogQLParser.OrderExprListContext):
        pass

    # Exit a parse tree produced by HogQLParser#orderExprList.
    def exitOrderExprList(self, ctx: HogQLParser.OrderExprListContext):
        pass

    # Enter a parse tree produced by HogQLParser#orderExpr.
    def enterOrderExpr(self, ctx: HogQLParser.OrderExprContext):
        pass

    # Exit a parse tree produced by HogQLParser#orderExpr.
    def exitOrderExpr(self, ctx: HogQLParser.OrderExprContext):
        pass

    # Enter a parse tree produced by HogQLParser#ratioExpr.
    def enterRatioExpr(self, ctx: HogQLParser.RatioExprContext):
        pass

    # Exit a parse tree produced by HogQLParser#ratioExpr.
    def exitRatioExpr(self, ctx: HogQLParser.RatioExprContext):
        pass

    # Enter a parse tree produced by HogQLParser#settingExprList.
    def enterSettingExprList(self, ctx: HogQLParser.SettingExprListContext):
        pass

    # Exit a parse tree produced by HogQLParser#settingExprList.
    def exitSettingExprList(self, ctx: HogQLParser.SettingExprListContext):
        pass

    # Enter a parse tree produced by HogQLParser#settingExpr.
    def enterSettingExpr(self, ctx: HogQLParser.SettingExprContext):
        pass

    # Exit a parse tree produced by HogQLParser#settingExpr.
    def exitSettingExpr(self, ctx: HogQLParser.SettingExprContext):
        pass

    # Enter a parse tree produced by HogQLParser#windowExpr.
    def enterWindowExpr(self, ctx: HogQLParser.WindowExprContext):
        pass

    # Exit a parse tree produced by HogQLParser#windowExpr.
    def exitWindowExpr(self, ctx: HogQLParser.WindowExprContext):
        pass

    # Enter a parse tree produced by HogQLParser#winPartitionByClause.
    def enterWinPartitionByClause(self, ctx: HogQLParser.WinPartitionByClauseContext):
        pass

    # Exit a parse tree produced by HogQLParser#winPartitionByClause.
    def exitWinPartitionByClause(self, ctx: HogQLParser.WinPartitionByClauseContext):
        pass

    # Enter a parse tree produced by HogQLParser#winOrderByClause.
    def enterWinOrderByClause(self, ctx: HogQLParser.WinOrderByClauseContext):
        pass

    # Exit a parse tree produced by HogQLParser#winOrderByClause.
    def exitWinOrderByClause(self, ctx: HogQLParser.WinOrderByClauseContext):
        pass

    # Enter a parse tree produced by HogQLParser#winFrameClause.
    def enterWinFrameClause(self, ctx: HogQLParser.WinFrameClauseContext):
        pass

    # Exit a parse tree produced by HogQLParser#winFrameClause.
    def exitWinFrameClause(self, ctx: HogQLParser.WinFrameClauseContext):
        pass

    # Enter a parse tree produced by HogQLParser#frameStart.
    def enterFrameStart(self, ctx: HogQLParser.FrameStartContext):
        pass

    # Exit a parse tree produced by HogQLParser#frameStart.
    def exitFrameStart(self, ctx: HogQLParser.FrameStartContext):
        pass

    # Enter a parse tree produced by HogQLParser#frameBetween.
    def enterFrameBetween(self, ctx: HogQLParser.FrameBetweenContext):
        pass

    # Exit a parse tree produced by HogQLParser#frameBetween.
    def exitFrameBetween(self, ctx: HogQLParser.FrameBetweenContext):
        pass

    # Enter a parse tree produced by HogQLParser#winFrameBound.
    def enterWinFrameBound(self, ctx: HogQLParser.WinFrameBoundContext):
        pass

    # Exit a parse tree produced by HogQLParser#winFrameBound.
    def exitWinFrameBound(self, ctx: HogQLParser.WinFrameBoundContext):
        pass

    # Enter a parse tree produced by HogQLParser#ColumnTypeExprSimple.
    def enterColumnTypeExprSimple(self, ctx: HogQLParser.ColumnTypeExprSimpleContext):
        pass

    # Exit a parse tree produced by HogQLParser#ColumnTypeExprSimple.
    def exitColumnTypeExprSimple(self, ctx: HogQLParser.ColumnTypeExprSimpleContext):
        pass

    # Enter a parse tree produced by HogQLParser#ColumnTypeExprNested.
    def enterColumnTypeExprNested(self, ctx: HogQLParser.ColumnTypeExprNestedContext):
        pass

    # Exit a parse tree produced by HogQLParser#ColumnTypeExprNested.
    def exitColumnTypeExprNested(self, ctx: HogQLParser.ColumnTypeExprNestedContext):
        pass

    # Enter a parse tree produced by HogQLParser#ColumnTypeExprEnum.
    def enterColumnTypeExprEnum(self, ctx: HogQLParser.ColumnTypeExprEnumContext):
        pass

    # Exit a parse tree produced by HogQLParser#ColumnTypeExprEnum.
    def exitColumnTypeExprEnum(self, ctx: HogQLParser.ColumnTypeExprEnumContext):
        pass

    # Enter a parse tree produced by HogQLParser#ColumnTypeExprComplex.
    def enterColumnTypeExprComplex(self, ctx: HogQLParser.ColumnTypeExprComplexContext):
        pass

    # Exit a parse tree produced by HogQLParser#ColumnTypeExprComplex.
    def exitColumnTypeExprComplex(self, ctx: HogQLParser.ColumnTypeExprComplexContext):
        pass

    # Enter a parse tree produced by HogQLParser#ColumnTypeExprParam.
    def enterColumnTypeExprParam(self, ctx: HogQLParser.ColumnTypeExprParamContext):
        pass

    # Exit a parse tree produced by HogQLParser#ColumnTypeExprParam.
    def exitColumnTypeExprParam(self, ctx: HogQLParser.ColumnTypeExprParamContext):
        pass

    # Enter a parse tree produced by HogQLParser#columnExprList.
    def enterColumnExprList(self, ctx: HogQLParser.ColumnExprListContext):
        pass

    # Exit a parse tree produced by HogQLParser#columnExprList.
    def exitColumnExprList(self, ctx: HogQLParser.ColumnExprListContext):
        pass

    # Enter a parse tree produced by HogQLParser#ColumnsExprAsterisk.
    def enterColumnsExprAsterisk(self, ctx: HogQLParser.ColumnsExprAsteriskContext):
        pass

    # Exit a parse tree produced by HogQLParser#ColumnsExprAsterisk.
    def exitColumnsExprAsterisk(self, ctx: HogQLParser.ColumnsExprAsteriskContext):
        pass

    # Enter a parse tree produced by HogQLParser#ColumnsExprSubquery.
    def enterColumnsExprSubquery(self, ctx: HogQLParser.ColumnsExprSubqueryContext):
        pass

    # Exit a parse tree produced by HogQLParser#ColumnsExprSubquery.
    def exitColumnsExprSubquery(self, ctx: HogQLParser.ColumnsExprSubqueryContext):
        pass

    # Enter a parse tree produced by HogQLParser#ColumnsExprColumn.
    def enterColumnsExprColumn(self, ctx: HogQLParser.ColumnsExprColumnContext):
        pass

    # Exit a parse tree produced by HogQLParser#ColumnsExprColumn.
    def exitColumnsExprColumn(self, ctx: HogQLParser.ColumnsExprColumnContext):
        pass

    # Enter a parse tree produced by HogQLParser#ColumnExprTernaryOp.
    def enterColumnExprTernaryOp(self, ctx: HogQLParser.ColumnExprTernaryOpContext):
        pass

    # Exit a parse tree produced by HogQLParser#ColumnExprTernaryOp.
    def exitColumnExprTernaryOp(self, ctx: HogQLParser.ColumnExprTernaryOpContext):
        pass

    # Enter a parse tree produced by HogQLParser#ColumnExprAlias.
    def enterColumnExprAlias(self, ctx: HogQLParser.ColumnExprAliasContext):
        pass

    # Exit a parse tree produced by HogQLParser#ColumnExprAlias.
    def exitColumnExprAlias(self, ctx: HogQLParser.ColumnExprAliasContext):
        pass

    # Enter a parse tree produced by HogQLParser#ColumnExprExtract.
    def enterColumnExprExtract(self, ctx: HogQLParser.ColumnExprExtractContext):
        pass

    # Exit a parse tree produced by HogQLParser#ColumnExprExtract.
    def exitColumnExprExtract(self, ctx: HogQLParser.ColumnExprExtractContext):
        pass

    # Enter a parse tree produced by HogQLParser#ColumnExprNegate.
    def enterColumnExprNegate(self, ctx: HogQLParser.ColumnExprNegateContext):
        pass

    # Exit a parse tree produced by HogQLParser#ColumnExprNegate.
    def exitColumnExprNegate(self, ctx: HogQLParser.ColumnExprNegateContext):
        pass

    # Enter a parse tree produced by HogQLParser#ColumnExprSubquery.
    def enterColumnExprSubquery(self, ctx: HogQLParser.ColumnExprSubqueryContext):
        pass

    # Exit a parse tree produced by HogQLParser#ColumnExprSubquery.
    def exitColumnExprSubquery(self, ctx: HogQLParser.ColumnExprSubqueryContext):
        pass

    # Enter a parse tree produced by HogQLParser#ColumnExprLiteral.
    def enterColumnExprLiteral(self, ctx: HogQLParser.ColumnExprLiteralContext):
        pass

    # Exit a parse tree produced by HogQLParser#ColumnExprLiteral.
    def exitColumnExprLiteral(self, ctx: HogQLParser.ColumnExprLiteralContext):
        pass

    # Enter a parse tree produced by HogQLParser#ColumnExprArray.
    def enterColumnExprArray(self, ctx: HogQLParser.ColumnExprArrayContext):
        pass

    # Exit a parse tree produced by HogQLParser#ColumnExprArray.
    def exitColumnExprArray(self, ctx: HogQLParser.ColumnExprArrayContext):
        pass

    # Enter a parse tree produced by HogQLParser#ColumnExprSubstring.
    def enterColumnExprSubstring(self, ctx: HogQLParser.ColumnExprSubstringContext):
        pass

    # Exit a parse tree produced by HogQLParser#ColumnExprSubstring.
    def exitColumnExprSubstring(self, ctx: HogQLParser.ColumnExprSubstringContext):
        pass

    # Enter a parse tree produced by HogQLParser#ColumnExprCast.
    def enterColumnExprCast(self, ctx: HogQLParser.ColumnExprCastContext):
        pass

    # Exit a parse tree produced by HogQLParser#ColumnExprCast.
    def exitColumnExprCast(self, ctx: HogQLParser.ColumnExprCastContext):
        pass

    # Enter a parse tree produced by HogQLParser#ColumnExprOr.
    def enterColumnExprOr(self, ctx: HogQLParser.ColumnExprOrContext):
        pass

    # Exit a parse tree produced by HogQLParser#ColumnExprOr.
    def exitColumnExprOr(self, ctx: HogQLParser.ColumnExprOrContext):
        pass

    # Enter a parse tree produced by HogQLParser#ColumnExprPrecedence1.
    def enterColumnExprPrecedence1(self, ctx: HogQLParser.ColumnExprPrecedence1Context):
        pass

    # Exit a parse tree produced by HogQLParser#ColumnExprPrecedence1.
    def exitColumnExprPrecedence1(self, ctx: HogQLParser.ColumnExprPrecedence1Context):
        pass

    # Enter a parse tree produced by HogQLParser#ColumnExprPrecedence2.
    def enterColumnExprPrecedence2(self, ctx: HogQLParser.ColumnExprPrecedence2Context):
        pass

    # Exit a parse tree produced by HogQLParser#ColumnExprPrecedence2.
    def exitColumnExprPrecedence2(self, ctx: HogQLParser.ColumnExprPrecedence2Context):
        pass

    # Enter a parse tree produced by HogQLParser#ColumnExprPrecedence3.
    def enterColumnExprPrecedence3(self, ctx: HogQLParser.ColumnExprPrecedence3Context):
        pass

    # Exit a parse tree produced by HogQLParser#ColumnExprPrecedence3.
    def exitColumnExprPrecedence3(self, ctx: HogQLParser.ColumnExprPrecedence3Context):
        pass

    # Enter a parse tree produced by HogQLParser#ColumnExprInterval.
    def enterColumnExprInterval(self, ctx: HogQLParser.ColumnExprIntervalContext):
        pass

    # Exit a parse tree produced by HogQLParser#ColumnExprInterval.
    def exitColumnExprInterval(self, ctx: HogQLParser.ColumnExprIntervalContext):
        pass

    # Enter a parse tree produced by HogQLParser#ColumnExprIsNull.
    def enterColumnExprIsNull(self, ctx: HogQLParser.ColumnExprIsNullContext):
        pass

    # Exit a parse tree produced by HogQLParser#ColumnExprIsNull.
    def exitColumnExprIsNull(self, ctx: HogQLParser.ColumnExprIsNullContext):
        pass

    # Enter a parse tree produced by HogQLParser#ColumnExprWinFunctionTarget.
    def enterColumnExprWinFunctionTarget(self, ctx: HogQLParser.ColumnExprWinFunctionTargetContext):
        pass

    # Exit a parse tree produced by HogQLParser#ColumnExprWinFunctionTarget.
    def exitColumnExprWinFunctionTarget(self, ctx: HogQLParser.ColumnExprWinFunctionTargetContext):
        pass

    # Enter a parse tree produced by HogQLParser#ColumnExprTrim.
    def enterColumnExprTrim(self, ctx: HogQLParser.ColumnExprTrimContext):
        pass

    # Exit a parse tree produced by HogQLParser#ColumnExprTrim.
    def exitColumnExprTrim(self, ctx: HogQLParser.ColumnExprTrimContext):
        pass

    # Enter a parse tree produced by HogQLParser#ColumnExprTuple.
    def enterColumnExprTuple(self, ctx: HogQLParser.ColumnExprTupleContext):
        pass

    # Exit a parse tree produced by HogQLParser#ColumnExprTuple.
    def exitColumnExprTuple(self, ctx: HogQLParser.ColumnExprTupleContext):
        pass

    # Enter a parse tree produced by HogQLParser#ColumnExprArrayAccess.
    def enterColumnExprArrayAccess(self, ctx: HogQLParser.ColumnExprArrayAccessContext):
        pass

    # Exit a parse tree produced by HogQLParser#ColumnExprArrayAccess.
    def exitColumnExprArrayAccess(self, ctx: HogQLParser.ColumnExprArrayAccessContext):
        pass

    # Enter a parse tree produced by HogQLParser#ColumnExprBetween.
    def enterColumnExprBetween(self, ctx: HogQLParser.ColumnExprBetweenContext):
        pass

    # Exit a parse tree produced by HogQLParser#ColumnExprBetween.
    def exitColumnExprBetween(self, ctx: HogQLParser.ColumnExprBetweenContext):
        pass

    # Enter a parse tree produced by HogQLParser#ColumnExprParens.
    def enterColumnExprParens(self, ctx: HogQLParser.ColumnExprParensContext):
        pass

    # Exit a parse tree produced by HogQLParser#ColumnExprParens.
    def exitColumnExprParens(self, ctx: HogQLParser.ColumnExprParensContext):
        pass

    # Enter a parse tree produced by HogQLParser#ColumnExprTimestamp.
    def enterColumnExprTimestamp(self, ctx: HogQLParser.ColumnExprTimestampContext):
        pass

    # Exit a parse tree produced by HogQLParser#ColumnExprTimestamp.
    def exitColumnExprTimestamp(self, ctx: HogQLParser.ColumnExprTimestampContext):
        pass

    # Enter a parse tree produced by HogQLParser#ColumnExprAnd.
    def enterColumnExprAnd(self, ctx: HogQLParser.ColumnExprAndContext):
        pass

    # Exit a parse tree produced by HogQLParser#ColumnExprAnd.
    def exitColumnExprAnd(self, ctx: HogQLParser.ColumnExprAndContext):
        pass

    # Enter a parse tree produced by HogQLParser#ColumnExprTupleAccess.
    def enterColumnExprTupleAccess(self, ctx: HogQLParser.ColumnExprTupleAccessContext):
        pass

    # Exit a parse tree produced by HogQLParser#ColumnExprTupleAccess.
    def exitColumnExprTupleAccess(self, ctx: HogQLParser.ColumnExprTupleAccessContext):
        pass

    # Enter a parse tree produced by HogQLParser#ColumnExprCase.
    def enterColumnExprCase(self, ctx: HogQLParser.ColumnExprCaseContext):
        pass

    # Exit a parse tree produced by HogQLParser#ColumnExprCase.
    def exitColumnExprCase(self, ctx: HogQLParser.ColumnExprCaseContext):
        pass

    # Enter a parse tree produced by HogQLParser#ColumnExprDate.
    def enterColumnExprDate(self, ctx: HogQLParser.ColumnExprDateContext):
        pass

    # Exit a parse tree produced by HogQLParser#ColumnExprDate.
    def exitColumnExprDate(self, ctx: HogQLParser.ColumnExprDateContext):
        pass

    # Enter a parse tree produced by HogQLParser#ColumnExprNot.
    def enterColumnExprNot(self, ctx: HogQLParser.ColumnExprNotContext):
        pass

    # Exit a parse tree produced by HogQLParser#ColumnExprNot.
    def exitColumnExprNot(self, ctx: HogQLParser.ColumnExprNotContext):
        pass

    # Enter a parse tree produced by HogQLParser#ColumnExprWinFunction.
    def enterColumnExprWinFunction(self, ctx: HogQLParser.ColumnExprWinFunctionContext):
        pass

    # Exit a parse tree produced by HogQLParser#ColumnExprWinFunction.
    def exitColumnExprWinFunction(self, ctx: HogQLParser.ColumnExprWinFunctionContext):
        pass

    # Enter a parse tree produced by HogQLParser#ColumnExprIdentifier.
    def enterColumnExprIdentifier(self, ctx: HogQLParser.ColumnExprIdentifierContext):
        pass

    # Exit a parse tree produced by HogQLParser#ColumnExprIdentifier.
    def exitColumnExprIdentifier(self, ctx: HogQLParser.ColumnExprIdentifierContext):
        pass

    # Enter a parse tree produced by HogQLParser#ColumnExprFunction.
    def enterColumnExprFunction(self, ctx: HogQLParser.ColumnExprFunctionContext):
        pass

    # Exit a parse tree produced by HogQLParser#ColumnExprFunction.
    def exitColumnExprFunction(self, ctx: HogQLParser.ColumnExprFunctionContext):
        pass

    # Enter a parse tree produced by HogQLParser#ColumnExprAsterisk.
    def enterColumnExprAsterisk(self, ctx: HogQLParser.ColumnExprAsteriskContext):
        pass

    # Exit a parse tree produced by HogQLParser#ColumnExprAsterisk.
    def exitColumnExprAsterisk(self, ctx: HogQLParser.ColumnExprAsteriskContext):
        pass

    # Enter a parse tree produced by HogQLParser#columnArgList.
    def enterColumnArgList(self, ctx: HogQLParser.ColumnArgListContext):
        pass

    # Exit a parse tree produced by HogQLParser#columnArgList.
    def exitColumnArgList(self, ctx: HogQLParser.ColumnArgListContext):
        pass

    # Enter a parse tree produced by HogQLParser#columnArgExpr.
    def enterColumnArgExpr(self, ctx: HogQLParser.ColumnArgExprContext):
        pass

    # Exit a parse tree produced by HogQLParser#columnArgExpr.
    def exitColumnArgExpr(self, ctx: HogQLParser.ColumnArgExprContext):
        pass

    # Enter a parse tree produced by HogQLParser#columnLambdaExpr.
    def enterColumnLambdaExpr(self, ctx: HogQLParser.ColumnLambdaExprContext):
        pass

    # Exit a parse tree produced by HogQLParser#columnLambdaExpr.
    def exitColumnLambdaExpr(self, ctx: HogQLParser.ColumnLambdaExprContext):
        pass

    # Enter a parse tree produced by HogQLParser#columnIdentifier.
    def enterColumnIdentifier(self, ctx: HogQLParser.ColumnIdentifierContext):
        pass

    # Exit a parse tree produced by HogQLParser#columnIdentifier.
    def exitColumnIdentifier(self, ctx: HogQLParser.ColumnIdentifierContext):
        pass

    # Enter a parse tree produced by HogQLParser#nestedIdentifier.
    def enterNestedIdentifier(self, ctx: HogQLParser.NestedIdentifierContext):
        pass

    # Exit a parse tree produced by HogQLParser#nestedIdentifier.
    def exitNestedIdentifier(self, ctx: HogQLParser.NestedIdentifierContext):
        pass

    # Enter a parse tree produced by HogQLParser#TableExprIdentifier.
    def enterTableExprIdentifier(self, ctx: HogQLParser.TableExprIdentifierContext):
        pass

    # Exit a parse tree produced by HogQLParser#TableExprIdentifier.
    def exitTableExprIdentifier(self, ctx: HogQLParser.TableExprIdentifierContext):
        pass

    # Enter a parse tree produced by HogQLParser#TableExprSubquery.
    def enterTableExprSubquery(self, ctx: HogQLParser.TableExprSubqueryContext):
        pass

    # Exit a parse tree produced by HogQLParser#TableExprSubquery.
    def exitTableExprSubquery(self, ctx: HogQLParser.TableExprSubqueryContext):
        pass

    # Enter a parse tree produced by HogQLParser#TableExprAlias.
    def enterTableExprAlias(self, ctx: HogQLParser.TableExprAliasContext):
        pass

    # Exit a parse tree produced by HogQLParser#TableExprAlias.
    def exitTableExprAlias(self, ctx: HogQLParser.TableExprAliasContext):
        pass

    # Enter a parse tree produced by HogQLParser#TableExprFunction.
    def enterTableExprFunction(self, ctx: HogQLParser.TableExprFunctionContext):
        pass

    # Exit a parse tree produced by HogQLParser#TableExprFunction.
    def exitTableExprFunction(self, ctx: HogQLParser.TableExprFunctionContext):
        pass

    # Enter a parse tree produced by HogQLParser#tableFunctionExpr.
    def enterTableFunctionExpr(self, ctx: HogQLParser.TableFunctionExprContext):
        pass

    # Exit a parse tree produced by HogQLParser#tableFunctionExpr.
    def exitTableFunctionExpr(self, ctx: HogQLParser.TableFunctionExprContext):
        pass

    # Enter a parse tree produced by HogQLParser#tableIdentifier.
    def enterTableIdentifier(self, ctx: HogQLParser.TableIdentifierContext):
        pass

    # Exit a parse tree produced by HogQLParser#tableIdentifier.
    def exitTableIdentifier(self, ctx: HogQLParser.TableIdentifierContext):
        pass

    # Enter a parse tree produced by HogQLParser#tableArgList.
    def enterTableArgList(self, ctx: HogQLParser.TableArgListContext):
        pass

    # Exit a parse tree produced by HogQLParser#tableArgList.
    def exitTableArgList(self, ctx: HogQLParser.TableArgListContext):
        pass

    # Enter a parse tree produced by HogQLParser#tableArgExpr.
    def enterTableArgExpr(self, ctx: HogQLParser.TableArgExprContext):
        pass

    # Exit a parse tree produced by HogQLParser#tableArgExpr.
    def exitTableArgExpr(self, ctx: HogQLParser.TableArgExprContext):
        pass

    # Enter a parse tree produced by HogQLParser#databaseIdentifier.
    def enterDatabaseIdentifier(self, ctx: HogQLParser.DatabaseIdentifierContext):
        pass

    # Exit a parse tree produced by HogQLParser#databaseIdentifier.
    def exitDatabaseIdentifier(self, ctx: HogQLParser.DatabaseIdentifierContext):
        pass

    # Enter a parse tree produced by HogQLParser#floatingLiteral.
    def enterFloatingLiteral(self, ctx: HogQLParser.FloatingLiteralContext):
        pass

    # Exit a parse tree produced by HogQLParser#floatingLiteral.
    def exitFloatingLiteral(self, ctx: HogQLParser.FloatingLiteralContext):
        pass

    # Enter a parse tree produced by HogQLParser#numberLiteral.
    def enterNumberLiteral(self, ctx: HogQLParser.NumberLiteralContext):
        pass

    # Exit a parse tree produced by HogQLParser#numberLiteral.
    def exitNumberLiteral(self, ctx: HogQLParser.NumberLiteralContext):
        pass

    # Enter a parse tree produced by HogQLParser#literal.
    def enterLiteral(self, ctx: HogQLParser.LiteralContext):
        pass

    # Exit a parse tree produced by HogQLParser#literal.
    def exitLiteral(self, ctx: HogQLParser.LiteralContext):
        pass

    # Enter a parse tree produced by HogQLParser#interval.
    def enterInterval(self, ctx: HogQLParser.IntervalContext):
        pass

    # Exit a parse tree produced by HogQLParser#interval.
    def exitInterval(self, ctx: HogQLParser.IntervalContext):
        pass

    # Enter a parse tree produced by HogQLParser#keyword.
    def enterKeyword(self, ctx: HogQLParser.KeywordContext):
        pass

    # Exit a parse tree produced by HogQLParser#keyword.
    def exitKeyword(self, ctx: HogQLParser.KeywordContext):
        pass

    # Enter a parse tree produced by HogQLParser#keywordForAlias.
    def enterKeywordForAlias(self, ctx: HogQLParser.KeywordForAliasContext):
        pass

    # Exit a parse tree produced by HogQLParser#keywordForAlias.
    def exitKeywordForAlias(self, ctx: HogQLParser.KeywordForAliasContext):
        pass

    # Enter a parse tree produced by HogQLParser#alias.
    def enterAlias(self, ctx: HogQLParser.AliasContext):
        pass

    # Exit a parse tree produced by HogQLParser#alias.
    def exitAlias(self, ctx: HogQLParser.AliasContext):
        pass

    # Enter a parse tree produced by HogQLParser#identifier.
    def enterIdentifier(self, ctx: HogQLParser.IdentifierContext):
        pass

    # Exit a parse tree produced by HogQLParser#identifier.
    def exitIdentifier(self, ctx: HogQLParser.IdentifierContext):
        pass

    # Enter a parse tree produced by HogQLParser#identifierOrNull.
    def enterIdentifierOrNull(self, ctx: HogQLParser.IdentifierOrNullContext):
        pass

    # Exit a parse tree produced by HogQLParser#identifierOrNull.
    def exitIdentifierOrNull(self, ctx: HogQLParser.IdentifierOrNullContext):
        pass

    # Enter a parse tree produced by HogQLParser#enumValue.
    def enterEnumValue(self, ctx: HogQLParser.EnumValueContext):
        pass

    # Exit a parse tree produced by HogQLParser#enumValue.
    def exitEnumValue(self, ctx: HogQLParser.EnumValueContext):
        pass


del HogQLParser
