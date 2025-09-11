# Generated from HogQLParser.g4 by ANTLR 4.13.2
from antlr4 import *
if "." in __name__:
    from .HogQLParser import HogQLParser
else:
    from HogQLParser import HogQLParser

# This class defines a complete generic visitor for a parse tree produced by HogQLParser.

class HogQLParserVisitor(ParseTreeVisitor):

    # Visit a parse tree produced by HogQLParser#program.
    def visitProgram(self, ctx:HogQLParser.ProgramContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#declaration.
    def visitDeclaration(self, ctx:HogQLParser.DeclarationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#expression.
    def visitExpression(self, ctx:HogQLParser.ExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#varDecl.
    def visitVarDecl(self, ctx:HogQLParser.VarDeclContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#identifierList.
    def visitIdentifierList(self, ctx:HogQLParser.IdentifierListContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#statement.
    def visitStatement(self, ctx:HogQLParser.StatementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#returnStmt.
    def visitReturnStmt(self, ctx:HogQLParser.ReturnStmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#throwStmt.
    def visitThrowStmt(self, ctx:HogQLParser.ThrowStmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#catchBlock.
    def visitCatchBlock(self, ctx:HogQLParser.CatchBlockContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#tryCatchStmt.
    def visitTryCatchStmt(self, ctx:HogQLParser.TryCatchStmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#ifStmt.
    def visitIfStmt(self, ctx:HogQLParser.IfStmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#whileStmt.
    def visitWhileStmt(self, ctx:HogQLParser.WhileStmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#forStmt.
    def visitForStmt(self, ctx:HogQLParser.ForStmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#forInStmt.
    def visitForInStmt(self, ctx:HogQLParser.ForInStmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#funcStmt.
    def visitFuncStmt(self, ctx:HogQLParser.FuncStmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#varAssignment.
    def visitVarAssignment(self, ctx:HogQLParser.VarAssignmentContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#exprStmt.
    def visitExprStmt(self, ctx:HogQLParser.ExprStmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#emptyStmt.
    def visitEmptyStmt(self, ctx:HogQLParser.EmptyStmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#block.
    def visitBlock(self, ctx:HogQLParser.BlockContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#kvPair.
    def visitKvPair(self, ctx:HogQLParser.KvPairContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#kvPairList.
    def visitKvPairList(self, ctx:HogQLParser.KvPairListContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#select.
    def visitSelect(self, ctx:HogQLParser.SelectContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#selectStmtWithParens.
    def visitSelectStmtWithParens(self, ctx:HogQLParser.SelectStmtWithParensContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#subsequentSelectSetClause.
    def visitSubsequentSelectSetClause(self, ctx:HogQLParser.SubsequentSelectSetClauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#selectSetStmt.
    def visitSelectSetStmt(self, ctx:HogQLParser.SelectSetStmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#selectStmt.
    def visitSelectStmt(self, ctx:HogQLParser.SelectStmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#withClause.
    def visitWithClause(self, ctx:HogQLParser.WithClauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#topClause.
    def visitTopClause(self, ctx:HogQLParser.TopClauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#fromClause.
    def visitFromClause(self, ctx:HogQLParser.FromClauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#arrayJoinClause.
    def visitArrayJoinClause(self, ctx:HogQLParser.ArrayJoinClauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#windowClause.
    def visitWindowClause(self, ctx:HogQLParser.WindowClauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#prewhereClause.
    def visitPrewhereClause(self, ctx:HogQLParser.PrewhereClauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#whereClause.
    def visitWhereClause(self, ctx:HogQLParser.WhereClauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#groupByClause.
    def visitGroupByClause(self, ctx:HogQLParser.GroupByClauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#havingClause.
    def visitHavingClause(self, ctx:HogQLParser.HavingClauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#orderByClause.
    def visitOrderByClause(self, ctx:HogQLParser.OrderByClauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#projectionOrderByClause.
    def visitProjectionOrderByClause(self, ctx:HogQLParser.ProjectionOrderByClauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#limitByClause.
    def visitLimitByClause(self, ctx:HogQLParser.LimitByClauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#limitAndOffsetClause.
    def visitLimitAndOffsetClause(self, ctx:HogQLParser.LimitAndOffsetClauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#offsetOnlyClause.
    def visitOffsetOnlyClause(self, ctx:HogQLParser.OffsetOnlyClauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#settingsClause.
    def visitSettingsClause(self, ctx:HogQLParser.SettingsClauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#JoinExprOp.
    def visitJoinExprOp(self, ctx:HogQLParser.JoinExprOpContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#JoinExprTable.
    def visitJoinExprTable(self, ctx:HogQLParser.JoinExprTableContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#JoinExprParens.
    def visitJoinExprParens(self, ctx:HogQLParser.JoinExprParensContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#JoinExprCrossOp.
    def visitJoinExprCrossOp(self, ctx:HogQLParser.JoinExprCrossOpContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#JoinOpInner.
    def visitJoinOpInner(self, ctx:HogQLParser.JoinOpInnerContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#JoinOpLeftRight.
    def visitJoinOpLeftRight(self, ctx:HogQLParser.JoinOpLeftRightContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#JoinOpFull.
    def visitJoinOpFull(self, ctx:HogQLParser.JoinOpFullContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#joinOpCross.
    def visitJoinOpCross(self, ctx:HogQLParser.JoinOpCrossContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#joinConstraintClause.
    def visitJoinConstraintClause(self, ctx:HogQLParser.JoinConstraintClauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#sampleClause.
    def visitSampleClause(self, ctx:HogQLParser.SampleClauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#limitExpr.
    def visitLimitExpr(self, ctx:HogQLParser.LimitExprContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#orderExprList.
    def visitOrderExprList(self, ctx:HogQLParser.OrderExprListContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#orderExpr.
    def visitOrderExpr(self, ctx:HogQLParser.OrderExprContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#ratioExpr.
    def visitRatioExpr(self, ctx:HogQLParser.RatioExprContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#settingExprList.
    def visitSettingExprList(self, ctx:HogQLParser.SettingExprListContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#settingExpr.
    def visitSettingExpr(self, ctx:HogQLParser.SettingExprContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#windowExpr.
    def visitWindowExpr(self, ctx:HogQLParser.WindowExprContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#winPartitionByClause.
    def visitWinPartitionByClause(self, ctx:HogQLParser.WinPartitionByClauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#winOrderByClause.
    def visitWinOrderByClause(self, ctx:HogQLParser.WinOrderByClauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#winFrameClause.
    def visitWinFrameClause(self, ctx:HogQLParser.WinFrameClauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#frameStart.
    def visitFrameStart(self, ctx:HogQLParser.FrameStartContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#frameBetween.
    def visitFrameBetween(self, ctx:HogQLParser.FrameBetweenContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#winFrameBound.
    def visitWinFrameBound(self, ctx:HogQLParser.WinFrameBoundContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#expr.
    def visitExpr(self, ctx:HogQLParser.ExprContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#ColumnTypeExprSimple.
    def visitColumnTypeExprSimple(self, ctx:HogQLParser.ColumnTypeExprSimpleContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#ColumnTypeExprNested.
    def visitColumnTypeExprNested(self, ctx:HogQLParser.ColumnTypeExprNestedContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#ColumnTypeExprEnum.
    def visitColumnTypeExprEnum(self, ctx:HogQLParser.ColumnTypeExprEnumContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#ColumnTypeExprComplex.
    def visitColumnTypeExprComplex(self, ctx:HogQLParser.ColumnTypeExprComplexContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#ColumnTypeExprParam.
    def visitColumnTypeExprParam(self, ctx:HogQLParser.ColumnTypeExprParamContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#columnExprList.
    def visitColumnExprList(self, ctx:HogQLParser.ColumnExprListContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#ColumnExprTernaryOp.
    def visitColumnExprTernaryOp(self, ctx:HogQLParser.ColumnExprTernaryOpContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#ColumnExprAlias.
    def visitColumnExprAlias(self, ctx:HogQLParser.ColumnExprAliasContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#ColumnExprNegate.
    def visitColumnExprNegate(self, ctx:HogQLParser.ColumnExprNegateContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#ColumnExprDict.
    def visitColumnExprDict(self, ctx:HogQLParser.ColumnExprDictContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#ColumnExprSubquery.
    def visitColumnExprSubquery(self, ctx:HogQLParser.ColumnExprSubqueryContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#ColumnExprLiteral.
    def visitColumnExprLiteral(self, ctx:HogQLParser.ColumnExprLiteralContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#ColumnExprArray.
    def visitColumnExprArray(self, ctx:HogQLParser.ColumnExprArrayContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#ColumnExprSubstring.
    def visitColumnExprSubstring(self, ctx:HogQLParser.ColumnExprSubstringContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#ColumnExprCast.
    def visitColumnExprCast(self, ctx:HogQLParser.ColumnExprCastContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#ColumnExprOr.
    def visitColumnExprOr(self, ctx:HogQLParser.ColumnExprOrContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#ColumnExprNullTupleAccess.
    def visitColumnExprNullTupleAccess(self, ctx:HogQLParser.ColumnExprNullTupleAccessContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#ColumnExprPrecedence1.
    def visitColumnExprPrecedence1(self, ctx:HogQLParser.ColumnExprPrecedence1Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#ColumnExprPrecedence2.
    def visitColumnExprPrecedence2(self, ctx:HogQLParser.ColumnExprPrecedence2Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#ColumnExprPrecedence3.
    def visitColumnExprPrecedence3(self, ctx:HogQLParser.ColumnExprPrecedence3Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#ColumnExprInterval.
    def visitColumnExprInterval(self, ctx:HogQLParser.ColumnExprIntervalContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#ColumnExprCallSelect.
    def visitColumnExprCallSelect(self, ctx:HogQLParser.ColumnExprCallSelectContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#ColumnExprIsNull.
    def visitColumnExprIsNull(self, ctx:HogQLParser.ColumnExprIsNullContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#ColumnExprWinFunctionTarget.
    def visitColumnExprWinFunctionTarget(self, ctx:HogQLParser.ColumnExprWinFunctionTargetContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#ColumnExprNullPropertyAccess.
    def visitColumnExprNullPropertyAccess(self, ctx:HogQLParser.ColumnExprNullPropertyAccessContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#ColumnExprIntervalString.
    def visitColumnExprIntervalString(self, ctx:HogQLParser.ColumnExprIntervalStringContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#ColumnExprTrim.
    def visitColumnExprTrim(self, ctx:HogQLParser.ColumnExprTrimContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#ColumnExprTagElement.
    def visitColumnExprTagElement(self, ctx:HogQLParser.ColumnExprTagElementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#ColumnExprTemplateString.
    def visitColumnExprTemplateString(self, ctx:HogQLParser.ColumnExprTemplateStringContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#ColumnExprTuple.
    def visitColumnExprTuple(self, ctx:HogQLParser.ColumnExprTupleContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#ColumnExprCall.
    def visitColumnExprCall(self, ctx:HogQLParser.ColumnExprCallContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#ColumnExprArrayAccess.
    def visitColumnExprArrayAccess(self, ctx:HogQLParser.ColumnExprArrayAccessContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#ColumnExprBetween.
    def visitColumnExprBetween(self, ctx:HogQLParser.ColumnExprBetweenContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#ColumnExprPropertyAccess.
    def visitColumnExprPropertyAccess(self, ctx:HogQLParser.ColumnExprPropertyAccessContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#ColumnExprParens.
    def visitColumnExprParens(self, ctx:HogQLParser.ColumnExprParensContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#ColumnExprNullArrayAccess.
    def visitColumnExprNullArrayAccess(self, ctx:HogQLParser.ColumnExprNullArrayAccessContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#ColumnExprTimestamp.
    def visitColumnExprTimestamp(self, ctx:HogQLParser.ColumnExprTimestampContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#ColumnExprNullish.
    def visitColumnExprNullish(self, ctx:HogQLParser.ColumnExprNullishContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#ColumnExprAnd.
    def visitColumnExprAnd(self, ctx:HogQLParser.ColumnExprAndContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#ColumnExprTupleAccess.
    def visitColumnExprTupleAccess(self, ctx:HogQLParser.ColumnExprTupleAccessContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#ColumnExprCase.
    def visitColumnExprCase(self, ctx:HogQLParser.ColumnExprCaseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#ColumnExprDate.
    def visitColumnExprDate(self, ctx:HogQLParser.ColumnExprDateContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#ColumnExprNot.
    def visitColumnExprNot(self, ctx:HogQLParser.ColumnExprNotContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#ColumnExprWinFunction.
    def visitColumnExprWinFunction(self, ctx:HogQLParser.ColumnExprWinFunctionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#ColumnExprLambda.
    def visitColumnExprLambda(self, ctx:HogQLParser.ColumnExprLambdaContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#ColumnExprIdentifier.
    def visitColumnExprIdentifier(self, ctx:HogQLParser.ColumnExprIdentifierContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#ColumnExprFunction.
    def visitColumnExprFunction(self, ctx:HogQLParser.ColumnExprFunctionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#ColumnExprAsterisk.
    def visitColumnExprAsterisk(self, ctx:HogQLParser.ColumnExprAsteriskContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#columnLambdaExpr.
    def visitColumnLambdaExpr(self, ctx:HogQLParser.ColumnLambdaExprContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#hogqlxChildElement.
    def visitHogqlxChildElement(self, ctx:HogQLParser.HogqlxChildElementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#hogqlxText.
    def visitHogqlxText(self, ctx:HogQLParser.HogqlxTextContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#HogqlxTagElementClosed.
    def visitHogqlxTagElementClosed(self, ctx:HogQLParser.HogqlxTagElementClosedContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#HogqlxTagElementNested.
    def visitHogqlxTagElementNested(self, ctx:HogQLParser.HogqlxTagElementNestedContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#hogqlxTagAttribute.
    def visitHogqlxTagAttribute(self, ctx:HogQLParser.HogqlxTagAttributeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#withExprList.
    def visitWithExprList(self, ctx:HogQLParser.WithExprListContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#WithExprSubquery.
    def visitWithExprSubquery(self, ctx:HogQLParser.WithExprSubqueryContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#WithExprColumn.
    def visitWithExprColumn(self, ctx:HogQLParser.WithExprColumnContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#columnIdentifier.
    def visitColumnIdentifier(self, ctx:HogQLParser.ColumnIdentifierContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#nestedIdentifier.
    def visitNestedIdentifier(self, ctx:HogQLParser.NestedIdentifierContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#TableExprTag.
    def visitTableExprTag(self, ctx:HogQLParser.TableExprTagContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#TableExprIdentifier.
    def visitTableExprIdentifier(self, ctx:HogQLParser.TableExprIdentifierContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#TableExprPlaceholder.
    def visitTableExprPlaceholder(self, ctx:HogQLParser.TableExprPlaceholderContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#TableExprSubquery.
    def visitTableExprSubquery(self, ctx:HogQLParser.TableExprSubqueryContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#TableExprAlias.
    def visitTableExprAlias(self, ctx:HogQLParser.TableExprAliasContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#TableExprFunction.
    def visitTableExprFunction(self, ctx:HogQLParser.TableExprFunctionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#tableFunctionExpr.
    def visitTableFunctionExpr(self, ctx:HogQLParser.TableFunctionExprContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#tableIdentifier.
    def visitTableIdentifier(self, ctx:HogQLParser.TableIdentifierContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#tableArgList.
    def visitTableArgList(self, ctx:HogQLParser.TableArgListContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#databaseIdentifier.
    def visitDatabaseIdentifier(self, ctx:HogQLParser.DatabaseIdentifierContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#floatingLiteral.
    def visitFloatingLiteral(self, ctx:HogQLParser.FloatingLiteralContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#numberLiteral.
    def visitNumberLiteral(self, ctx:HogQLParser.NumberLiteralContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#literal.
    def visitLiteral(self, ctx:HogQLParser.LiteralContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#interval.
    def visitInterval(self, ctx:HogQLParser.IntervalContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#keyword.
    def visitKeyword(self, ctx:HogQLParser.KeywordContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#keywordForAlias.
    def visitKeywordForAlias(self, ctx:HogQLParser.KeywordForAliasContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#alias.
    def visitAlias(self, ctx:HogQLParser.AliasContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#identifier.
    def visitIdentifier(self, ctx:HogQLParser.IdentifierContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#enumValue.
    def visitEnumValue(self, ctx:HogQLParser.EnumValueContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#placeholder.
    def visitPlaceholder(self, ctx:HogQLParser.PlaceholderContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#string.
    def visitString(self, ctx:HogQLParser.StringContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#templateString.
    def visitTemplateString(self, ctx:HogQLParser.TemplateStringContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#stringContents.
    def visitStringContents(self, ctx:HogQLParser.StringContentsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#fullTemplateString.
    def visitFullTemplateString(self, ctx:HogQLParser.FullTemplateStringContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by HogQLParser#stringContentsFull.
    def visitStringContentsFull(self, ctx:HogQLParser.StringContentsFullContext):
        return self.visitChildren(ctx)



del HogQLParser