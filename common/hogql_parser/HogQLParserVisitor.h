
// Generated from HogQLParser.g4 by ANTLR 4.13.2

#pragma once


#include "antlr4-runtime.h"
#include "HogQLParser.h"



/**
 * This class defines an abstract visitor for a parse tree
 * produced by HogQLParser.
 */
class  HogQLParserVisitor : public antlr4::tree::AbstractParseTreeVisitor {
public:

  /**
   * Visit parse trees produced by HogQLParser.
   */
    virtual std::any visitProgram(HogQLParser::ProgramContext *context) = 0;

    virtual std::any visitDeclaration(HogQLParser::DeclarationContext *context) = 0;

    virtual std::any visitExpression(HogQLParser::ExpressionContext *context) = 0;

    virtual std::any visitVarDecl(HogQLParser::VarDeclContext *context) = 0;

    virtual std::any visitIdentifierList(HogQLParser::IdentifierListContext *context) = 0;

    virtual std::any visitStatement(HogQLParser::StatementContext *context) = 0;

    virtual std::any visitReturnStmt(HogQLParser::ReturnStmtContext *context) = 0;

    virtual std::any visitThrowStmt(HogQLParser::ThrowStmtContext *context) = 0;

    virtual std::any visitCatchBlock(HogQLParser::CatchBlockContext *context) = 0;

    virtual std::any visitTryCatchStmt(HogQLParser::TryCatchStmtContext *context) = 0;

    virtual std::any visitIfStmt(HogQLParser::IfStmtContext *context) = 0;

    virtual std::any visitWhileStmt(HogQLParser::WhileStmtContext *context) = 0;

    virtual std::any visitForStmt(HogQLParser::ForStmtContext *context) = 0;

    virtual std::any visitForInStmt(HogQLParser::ForInStmtContext *context) = 0;

    virtual std::any visitFuncStmt(HogQLParser::FuncStmtContext *context) = 0;

    virtual std::any visitVarAssignment(HogQLParser::VarAssignmentContext *context) = 0;

    virtual std::any visitExprStmt(HogQLParser::ExprStmtContext *context) = 0;

    virtual std::any visitEmptyStmt(HogQLParser::EmptyStmtContext *context) = 0;

    virtual std::any visitBlock(HogQLParser::BlockContext *context) = 0;

    virtual std::any visitKvPair(HogQLParser::KvPairContext *context) = 0;

    virtual std::any visitKvPairList(HogQLParser::KvPairListContext *context) = 0;

    virtual std::any visitSelect(HogQLParser::SelectContext *context) = 0;

    virtual std::any visitSelectStmtWithParens(HogQLParser::SelectStmtWithParensContext *context) = 0;

    virtual std::any visitSubsequentSelectSetClause(HogQLParser::SubsequentSelectSetClauseContext *context) = 0;

    virtual std::any visitSelectSetStmt(HogQLParser::SelectSetStmtContext *context) = 0;

    virtual std::any visitLimitAndOffsetClauseOptional(HogQLParser::LimitAndOffsetClauseOptionalContext *context) = 0;

    virtual std::any visitSelectStmt(HogQLParser::SelectStmtContext *context) = 0;

    virtual std::any visitWithClause(HogQLParser::WithClauseContext *context) = 0;

    virtual std::any visitTopClause(HogQLParser::TopClauseContext *context) = 0;

    virtual std::any visitFromClause(HogQLParser::FromClauseContext *context) = 0;

    virtual std::any visitArrayJoinClause(HogQLParser::ArrayJoinClauseContext *context) = 0;

    virtual std::any visitWindowClause(HogQLParser::WindowClauseContext *context) = 0;

    virtual std::any visitPrewhereClause(HogQLParser::PrewhereClauseContext *context) = 0;

    virtual std::any visitWhereClause(HogQLParser::WhereClauseContext *context) = 0;

    virtual std::any visitGroupByClause(HogQLParser::GroupByClauseContext *context) = 0;

    virtual std::any visitGroupingSetList(HogQLParser::GroupingSetListContext *context) = 0;

    virtual std::any visitGroupingSet(HogQLParser::GroupingSetContext *context) = 0;

    virtual std::any visitHavingClause(HogQLParser::HavingClauseContext *context) = 0;

    virtual std::any visitQualifyClause(HogQLParser::QualifyClauseContext *context) = 0;

    virtual std::any visitOrderByClause(HogQLParser::OrderByClauseContext *context) = 0;

    virtual std::any visitInterpolateClause(HogQLParser::InterpolateClauseContext *context) = 0;

    virtual std::any visitProjectionOrderByClause(HogQLParser::ProjectionOrderByClauseContext *context) = 0;

    virtual std::any visitLimitByClause(HogQLParser::LimitByClauseContext *context) = 0;

    virtual std::any visitLimitAndOffsetClause(HogQLParser::LimitAndOffsetClauseContext *context) = 0;

    virtual std::any visitOffsetOnlyClause(HogQLParser::OffsetOnlyClauseContext *context) = 0;

    virtual std::any visitSettingsClause(HogQLParser::SettingsClauseContext *context) = 0;

    virtual std::any visitValuesClause(HogQLParser::ValuesClauseContext *context) = 0;

    virtual std::any visitValuesRow(HogQLParser::ValuesRowContext *context) = 0;

    virtual std::any visitJoinExprPositional(HogQLParser::JoinExprPositionalContext *context) = 0;

    virtual std::any visitJoinExprOp(HogQLParser::JoinExprOpContext *context) = 0;

    virtual std::any visitJoinExprTable(HogQLParser::JoinExprTableContext *context) = 0;

    virtual std::any visitJoinExprUnpivot(HogQLParser::JoinExprUnpivotContext *context) = 0;

    virtual std::any visitJoinExprParens(HogQLParser::JoinExprParensContext *context) = 0;

    virtual std::any visitJoinExprCrossOp(HogQLParser::JoinExprCrossOpContext *context) = 0;

    virtual std::any visitJoinExprPivot(HogQLParser::JoinExprPivotContext *context) = 0;

    virtual std::any visitJoinOpInner(HogQLParser::JoinOpInnerContext *context) = 0;

    virtual std::any visitJoinOpLeftRight(HogQLParser::JoinOpLeftRightContext *context) = 0;

    virtual std::any visitJoinOpFull(HogQLParser::JoinOpFullContext *context) = 0;

    virtual std::any visitJoinOpCross(HogQLParser::JoinOpCrossContext *context) = 0;

    virtual std::any visitJoinConstraintClause(HogQLParser::JoinConstraintClauseContext *context) = 0;

    virtual std::any visitSampleClause(HogQLParser::SampleClauseContext *context) = 0;

    virtual std::any visitLimitExpr(HogQLParser::LimitExprContext *context) = 0;

    virtual std::any visitOrderExprList(HogQLParser::OrderExprListContext *context) = 0;

    virtual std::any visitOrderExpr(HogQLParser::OrderExprContext *context) = 0;

    virtual std::any visitWithFillClause(HogQLParser::WithFillClauseContext *context) = 0;

    virtual std::any visitInterpolateExpr(HogQLParser::InterpolateExprContext *context) = 0;

    virtual std::any visitRatioExpr(HogQLParser::RatioExprContext *context) = 0;

    virtual std::any visitSettingExprList(HogQLParser::SettingExprListContext *context) = 0;

    virtual std::any visitSettingExpr(HogQLParser::SettingExprContext *context) = 0;

    virtual std::any visitWindowExpr(HogQLParser::WindowExprContext *context) = 0;

    virtual std::any visitWinPartitionByClause(HogQLParser::WinPartitionByClauseContext *context) = 0;

    virtual std::any visitWinOrderByClause(HogQLParser::WinOrderByClauseContext *context) = 0;

    virtual std::any visitWithinGroupClause(HogQLParser::WithinGroupClauseContext *context) = 0;

    virtual std::any visitWinFrameClause(HogQLParser::WinFrameClauseContext *context) = 0;

    virtual std::any visitFrameStart(HogQLParser::FrameStartContext *context) = 0;

    virtual std::any visitFrameBetween(HogQLParser::FrameBetweenContext *context) = 0;

    virtual std::any visitWinFrameBound(HogQLParser::WinFrameBoundContext *context) = 0;

    virtual std::any visitExpr(HogQLParser::ExprContext *context) = 0;

    virtual std::any visitColumnTypeExprNested(HogQLParser::ColumnTypeExprNestedContext *context) = 0;

    virtual std::any visitColumnTypeExprParam(HogQLParser::ColumnTypeExprParamContext *context) = 0;

    virtual std::any visitColumnTypeExprArray(HogQLParser::ColumnTypeExprArrayContext *context) = 0;

    virtual std::any visitColumnTypeExprComplex(HogQLParser::ColumnTypeExprComplexContext *context) = 0;

    virtual std::any visitColumnTypeExprSimple(HogQLParser::ColumnTypeExprSimpleContext *context) = 0;

    virtual std::any visitColumnTypeExprEnum(HogQLParser::ColumnTypeExprEnumContext *context) = 0;

    virtual std::any visitColumnTypeExprCompound(HogQLParser::ColumnTypeExprCompoundContext *context) = 0;

    virtual std::any visitColumnTypeCastExprWithTimeZone(HogQLParser::ColumnTypeCastExprWithTimeZoneContext *context) = 0;

    virtual std::any visitColumnTypeCastExprSimple(HogQLParser::ColumnTypeCastExprSimpleContext *context) = 0;

    virtual std::any visitColumnTypeCastIdentifier(HogQLParser::ColumnTypeCastIdentifierContext *context) = 0;

    virtual std::any visitKeywordForTypeCast(HogQLParser::KeywordForTypeCastContext *context) = 0;

    virtual std::any visitColumnExprList(HogQLParser::ColumnExprListContext *context) = 0;

    virtual std::any visitSelectColumnExprListBeforeFromTrailingComma(HogQLParser::SelectColumnExprListBeforeFromTrailingCommaContext *context) = 0;

    virtual std::any visitSelectColumnExprListBeforeFromPlain(HogQLParser::SelectColumnExprListBeforeFromPlainContext *context) = 0;

    virtual std::any visitSelectColumnExprList(HogQLParser::SelectColumnExprListContext *context) = 0;

    virtual std::any visitColumnExprAliasBefore(HogQLParser::ColumnExprAliasBeforeContext *context) = 0;

    virtual std::any visitColumnExprInvalidFromImplicitAlias(HogQLParser::ColumnExprInvalidFromImplicitAliasContext *context) = 0;

    virtual std::any visitColumnExprSelectValue(HogQLParser::ColumnExprSelectValueContext *context) = 0;

    virtual std::any visitColumnExprAliasImplicit(HogQLParser::ColumnExprAliasImplicitContext *context) = 0;

    virtual std::any visitColumnExprColumnsAll(HogQLParser::ColumnExprColumnsAllContext *context) = 0;

    virtual std::any visitColumnExprTernaryOp(HogQLParser::ColumnExprTernaryOpContext *context) = 0;

    virtual std::any visitColumnExprAlias(HogQLParser::ColumnExprAliasContext *context) = 0;

    virtual std::any visitColumnExprNegate(HogQLParser::ColumnExprNegateContext *context) = 0;

    virtual std::any visitColumnExprLiteral(HogQLParser::ColumnExprLiteralContext *context) = 0;

    virtual std::any visitColumnExprArray(HogQLParser::ColumnExprArrayContext *context) = 0;

    virtual std::any visitColumnExprOr(HogQLParser::ColumnExprOrContext *context) = 0;

    virtual std::any visitColumnExprPrecedence1(HogQLParser::ColumnExprPrecedence1Context *context) = 0;

    virtual std::any visitColumnExprPrecedence2(HogQLParser::ColumnExprPrecedence2Context *context) = 0;

    virtual std::any visitColumnExprPrecedence3(HogQLParser::ColumnExprPrecedence3Context *context) = 0;

    virtual std::any visitColumnExprInterval(HogQLParser::ColumnExprIntervalContext *context) = 0;

    virtual std::any visitColumnExprIsNull(HogQLParser::ColumnExprIsNullContext *context) = 0;

    virtual std::any visitColumnExprWinFunctionTarget(HogQLParser::ColumnExprWinFunctionTargetContext *context) = 0;

    virtual std::any visitColumnExprNamedArg(HogQLParser::ColumnExprNamedArgContext *context) = 0;

    virtual std::any visitColumnExprNullPropertyAccess(HogQLParser::ColumnExprNullPropertyAccessContext *context) = 0;

    virtual std::any visitColumnExprIntervalString(HogQLParser::ColumnExprIntervalStringContext *context) = 0;

    virtual std::any visitColumnExprTagElement(HogQLParser::ColumnExprTagElementContext *context) = 0;

    virtual std::any visitColumnExprCall(HogQLParser::ColumnExprCallContext *context) = 0;

    virtual std::any visitColumnExprArrayAccess(HogQLParser::ColumnExprArrayAccessContext *context) = 0;

    virtual std::any visitColumnExprBetween(HogQLParser::ColumnExprBetweenContext *context) = 0;

    virtual std::any visitColumnExprParens(HogQLParser::ColumnExprParensContext *context) = 0;

    virtual std::any visitColumnExprTimestamp(HogQLParser::ColumnExprTimestampContext *context) = 0;

    virtual std::any visitColumnExprAnd(HogQLParser::ColumnExprAndContext *context) = 0;

    virtual std::any visitColumnExprColumnsQualifiedExclude(HogQLParser::ColumnExprColumnsQualifiedExcludeContext *context) = 0;

    virtual std::any visitColumnExprNot(HogQLParser::ColumnExprNotContext *context) = 0;

    virtual std::any visitColumnExprFunction(HogQLParser::ColumnExprFunctionContext *context) = 0;

    virtual std::any visitColumnExprDict(HogQLParser::ColumnExprDictContext *context) = 0;

    virtual std::any visitColumnExprSubquery(HogQLParser::ColumnExprSubqueryContext *context) = 0;

    virtual std::any visitColumnExprSubstring(HogQLParser::ColumnExprSubstringContext *context) = 0;

    virtual std::any visitColumnExprCast(HogQLParser::ColumnExprCastContext *context) = 0;

    virtual std::any visitColumnExprArraySlice(HogQLParser::ColumnExprArraySliceContext *context) = 0;

    virtual std::any visitColumnExprColumnsQualifiedReplace(HogQLParser::ColumnExprColumnsQualifiedReplaceContext *context) = 0;

    virtual std::any visitColumnExprNullTupleAccess(HogQLParser::ColumnExprNullTupleAccessContext *context) = 0;

    virtual std::any visitColumnExprFunctionWithinGroup(HogQLParser::ColumnExprFunctionWithinGroupContext *context) = 0;

    virtual std::any visitColumnExprPositional(HogQLParser::ColumnExprPositionalContext *context) = 0;

    virtual std::any visitColumnExprColumnsRegex(HogQLParser::ColumnExprColumnsRegexContext *context) = 0;

    virtual std::any visitColumnExprTypeCast(HogQLParser::ColumnExprTypeCastContext *context) = 0;

    virtual std::any visitColumnExprIsDistinctFrom(HogQLParser::ColumnExprIsDistinctFromContext *context) = 0;

    virtual std::any visitColumnExprSpreadColumnsList(HogQLParser::ColumnExprSpreadColumnsListContext *context) = 0;

    virtual std::any visitColumnExprColumnsExcludeReplace(HogQLParser::ColumnExprColumnsExcludeReplaceContext *context) = 0;

    virtual std::any visitColumnExprColumnsQualifiedExcludeReplace(HogQLParser::ColumnExprColumnsQualifiedExcludeReplaceContext *context) = 0;

    virtual std::any visitColumnExprColumnsExclude(HogQLParser::ColumnExprColumnsExcludeContext *context) = 0;

    virtual std::any visitColumnExprColonLambda(HogQLParser::ColumnExprColonLambdaContext *context) = 0;

    virtual std::any visitColumnExprCallSelect(HogQLParser::ColumnExprCallSelectContext *context) = 0;

    virtual std::any visitColumnExprColumnsQualifiedAll(HogQLParser::ColumnExprColumnsQualifiedAllContext *context) = 0;

    virtual std::any visitColumnExprTrim(HogQLParser::ColumnExprTrimContext *context) = 0;

    virtual std::any visitColumnExprTemplateString(HogQLParser::ColumnExprTemplateStringContext *context) = 0;

    virtual std::any visitColumnExprTuple(HogQLParser::ColumnExprTupleContext *context) = 0;

    virtual std::any visitColumnExprTryCast(HogQLParser::ColumnExprTryCastContext *context) = 0;

    virtual std::any visitColumnExprColumnsList(HogQLParser::ColumnExprColumnsListContext *context) = 0;

    virtual std::any visitColumnExprColumnsReplace(HogQLParser::ColumnExprColumnsReplaceContext *context) = 0;

    virtual std::any visitColumnExprSpreadColumnsRegex(HogQLParser::ColumnExprSpreadColumnsRegexContext *context) = 0;

    virtual std::any visitColumnExprPropertyAccess(HogQLParser::ColumnExprPropertyAccessContext *context) = 0;

    virtual std::any visitColumnExprNullArrayAccess(HogQLParser::ColumnExprNullArrayAccessContext *context) = 0;

    virtual std::any visitColumnExprIgnoreNulls(HogQLParser::ColumnExprIgnoreNullsContext *context) = 0;

    virtual std::any visitColumnExprNullish(HogQLParser::ColumnExprNullishContext *context) = 0;

    virtual std::any visitColumnExprTupleAccess(HogQLParser::ColumnExprTupleAccessContext *context) = 0;

    virtual std::any visitColumnExprCase(HogQLParser::ColumnExprCaseContext *context) = 0;

    virtual std::any visitColumnExprDate(HogQLParser::ColumnExprDateContext *context) = 0;

    virtual std::any visitColumnExprWinFunction(HogQLParser::ColumnExprWinFunctionContext *context) = 0;

    virtual std::any visitColumnExprLambda(HogQLParser::ColumnExprLambdaContext *context) = 0;

    virtual std::any visitColumnExprIdentifier(HogQLParser::ColumnExprIdentifierContext *context) = 0;

    virtual std::any visitColumnExprAsterisk(HogQLParser::ColumnExprAsteriskContext *context) = 0;

    virtual std::any visitArrowLambda(HogQLParser::ArrowLambdaContext *context) = 0;

    virtual std::any visitColonLambda(HogQLParser::ColonLambdaContext *context) = 0;

    virtual std::any visitColumnsReplaceList(HogQLParser::ColumnsReplaceListContext *context) = 0;

    virtual std::any visitColumnsReplaceItem(HogQLParser::ColumnsReplaceItemContext *context) = 0;

    virtual std::any visitHogqlxChildElement(HogQLParser::HogqlxChildElementContext *context) = 0;

    virtual std::any visitHogqlxText(HogQLParser::HogqlxTextContext *context) = 0;

    virtual std::any visitHogqlxTagElementClosed(HogQLParser::HogqlxTagElementClosedContext *context) = 0;

    virtual std::any visitHogqlxTagElementNested(HogQLParser::HogqlxTagElementNestedContext *context) = 0;

    virtual std::any visitHogqlxTagAttribute(HogQLParser::HogqlxTagAttributeContext *context) = 0;

    virtual std::any visitWithExprList(HogQLParser::WithExprListContext *context) = 0;

    virtual std::any visitWithExprSubquery(HogQLParser::WithExprSubqueryContext *context) = 0;

    virtual std::any visitWithExprColumn(HogQLParser::WithExprColumnContext *context) = 0;

    virtual std::any visitWithExprColumnNameList(HogQLParser::WithExprColumnNameListContext *context) = 0;

    virtual std::any visitColumnIdentifier(HogQLParser::ColumnIdentifierContext *context) = 0;

    virtual std::any visitNestedIdentifier(HogQLParser::NestedIdentifierContext *context) = 0;

    virtual std::any visitTableExprTag(HogQLParser::TableExprTagContext *context) = 0;

    virtual std::any visitTableExprIdentifier(HogQLParser::TableExprIdentifierContext *context) = 0;

    virtual std::any visitTableExprPlaceholder(HogQLParser::TableExprPlaceholderContext *context) = 0;

    virtual std::any visitTableExprSubquery(HogQLParser::TableExprSubqueryContext *context) = 0;

    virtual std::any visitTableExprPivot(HogQLParser::TableExprPivotContext *context) = 0;

    virtual std::any visitTableExprValues(HogQLParser::TableExprValuesContext *context) = 0;

    virtual std::any visitTableExprAlias(HogQLParser::TableExprAliasContext *context) = 0;

    virtual std::any visitTableExprFunction(HogQLParser::TableExprFunctionContext *context) = 0;

    virtual std::any visitTableExprUnpivot(HogQLParser::TableExprUnpivotContext *context) = 0;

    virtual std::any visitPivotColumnList(HogQLParser::PivotColumnListContext *context) = 0;

    virtual std::any visitPivotColumn(HogQLParser::PivotColumnContext *context) = 0;

    virtual std::any visitUnpivotColumnList(HogQLParser::UnpivotColumnListContext *context) = 0;

    virtual std::any visitUnpivotColumn(HogQLParser::UnpivotColumnContext *context) = 0;

    virtual std::any visitColumnExprTupleOrSingle(HogQLParser::ColumnExprTupleOrSingleContext *context) = 0;

    virtual std::any visitColumnAliases(HogQLParser::ColumnAliasesContext *context) = 0;

    virtual std::any visitTableFunctionExpr(HogQLParser::TableFunctionExprContext *context) = 0;

    virtual std::any visitTableIdentifier(HogQLParser::TableIdentifierContext *context) = 0;

    virtual std::any visitTableArgList(HogQLParser::TableArgListContext *context) = 0;

    virtual std::any visitDatabaseIdentifier(HogQLParser::DatabaseIdentifierContext *context) = 0;

    virtual std::any visitFloatingLiteral(HogQLParser::FloatingLiteralContext *context) = 0;

    virtual std::any visitNumberLiteral(HogQLParser::NumberLiteralContext *context) = 0;

    virtual std::any visitLiteral(HogQLParser::LiteralContext *context) = 0;

    virtual std::any visitInterval(HogQLParser::IntervalContext *context) = 0;

    virtual std::any visitKeyword(HogQLParser::KeywordContext *context) = 0;

    virtual std::any visitKeywordForAlias(HogQLParser::KeywordForAliasContext *context) = 0;

    virtual std::any visitKeywordForImplicitAlias(HogQLParser::KeywordForImplicitAliasContext *context) = 0;

    virtual std::any visitAlias(HogQLParser::AliasContext *context) = 0;

    virtual std::any visitImplicitAlias(HogQLParser::ImplicitAliasContext *context) = 0;

    virtual std::any visitIdentifier(HogQLParser::IdentifierContext *context) = 0;

    virtual std::any visitEnumValue(HogQLParser::EnumValueContext *context) = 0;

    virtual std::any visitPlaceholder(HogQLParser::PlaceholderContext *context) = 0;

    virtual std::any visitString(HogQLParser::StringContext *context) = 0;

    virtual std::any visitTemplateString(HogQLParser::TemplateStringContext *context) = 0;

    virtual std::any visitStringContents(HogQLParser::StringContentsContext *context) = 0;

    virtual std::any visitFullTemplateString(HogQLParser::FullTemplateStringContext *context) = 0;

    virtual std::any visitStringContentsFull(HogQLParser::StringContentsFullContext *context) = 0;


};

