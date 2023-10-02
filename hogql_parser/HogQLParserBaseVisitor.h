
// Generated from HogQLParser.g4 by ANTLR 4.13.0

#pragma once


#include "antlr4-runtime.h"
#include "HogQLParserVisitor.h"


/**
 * This class provides an empty implementation of HogQLParserVisitor, which can be
 * extended to create a visitor which only needs to handle a subset of the available methods.
 */
class  HogQLParserBaseVisitor : public HogQLParserVisitor {
public:

  virtual std::any visitSelect(HogQLParser::SelectContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitSelectUnionStmt(HogQLParser::SelectUnionStmtContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitSelectStmtWithParens(HogQLParser::SelectStmtWithParensContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitSelectStmt(HogQLParser::SelectStmtContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitWithClause(HogQLParser::WithClauseContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitTopClause(HogQLParser::TopClauseContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitFromClause(HogQLParser::FromClauseContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitArrayJoinClause(HogQLParser::ArrayJoinClauseContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitWindowClause(HogQLParser::WindowClauseContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitPrewhereClause(HogQLParser::PrewhereClauseContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitWhereClause(HogQLParser::WhereClauseContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitGroupByClause(HogQLParser::GroupByClauseContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitHavingClause(HogQLParser::HavingClauseContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitOrderByClause(HogQLParser::OrderByClauseContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitProjectionOrderByClause(HogQLParser::ProjectionOrderByClauseContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitLimitAndOffsetClause(HogQLParser::LimitAndOffsetClauseContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitOffsetOnlyClause(HogQLParser::OffsetOnlyClauseContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitSettingsClause(HogQLParser::SettingsClauseContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitJoinExprOp(HogQLParser::JoinExprOpContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitJoinExprTable(HogQLParser::JoinExprTableContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitJoinExprParens(HogQLParser::JoinExprParensContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitJoinExprCrossOp(HogQLParser::JoinExprCrossOpContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitJoinOpInner(HogQLParser::JoinOpInnerContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitJoinOpLeftRight(HogQLParser::JoinOpLeftRightContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitJoinOpFull(HogQLParser::JoinOpFullContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitJoinOpCross(HogQLParser::JoinOpCrossContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitJoinConstraintClause(HogQLParser::JoinConstraintClauseContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitSampleClause(HogQLParser::SampleClauseContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitOrderExprList(HogQLParser::OrderExprListContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitOrderExpr(HogQLParser::OrderExprContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitRatioExpr(HogQLParser::RatioExprContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitSettingExprList(HogQLParser::SettingExprListContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitSettingExpr(HogQLParser::SettingExprContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitWindowExpr(HogQLParser::WindowExprContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitWinPartitionByClause(HogQLParser::WinPartitionByClauseContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitWinOrderByClause(HogQLParser::WinOrderByClauseContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitWinFrameClause(HogQLParser::WinFrameClauseContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitFrameStart(HogQLParser::FrameStartContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitFrameBetween(HogQLParser::FrameBetweenContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitWinFrameBound(HogQLParser::WinFrameBoundContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitExpr(HogQLParser::ExprContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitColumnTypeExprSimple(HogQLParser::ColumnTypeExprSimpleContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitColumnTypeExprNested(HogQLParser::ColumnTypeExprNestedContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitColumnTypeExprEnum(HogQLParser::ColumnTypeExprEnumContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitColumnTypeExprComplex(HogQLParser::ColumnTypeExprComplexContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitColumnTypeExprParam(HogQLParser::ColumnTypeExprParamContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitColumnExprList(HogQLParser::ColumnExprListContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitColumnExprTernaryOp(HogQLParser::ColumnExprTernaryOpContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitColumnExprAlias(HogQLParser::ColumnExprAliasContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitColumnExprExtract(HogQLParser::ColumnExprExtractContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitColumnExprNegate(HogQLParser::ColumnExprNegateContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitColumnExprSubquery(HogQLParser::ColumnExprSubqueryContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitColumnExprLiteral(HogQLParser::ColumnExprLiteralContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitColumnExprArray(HogQLParser::ColumnExprArrayContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitColumnExprSubstring(HogQLParser::ColumnExprSubstringContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitColumnExprCast(HogQLParser::ColumnExprCastContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitColumnExprOr(HogQLParser::ColumnExprOrContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitColumnExprPrecedence1(HogQLParser::ColumnExprPrecedence1Context *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitColumnExprPrecedence2(HogQLParser::ColumnExprPrecedence2Context *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitColumnExprPrecedence3(HogQLParser::ColumnExprPrecedence3Context *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitColumnExprInterval(HogQLParser::ColumnExprIntervalContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitColumnExprIsNull(HogQLParser::ColumnExprIsNullContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitColumnExprWinFunctionTarget(HogQLParser::ColumnExprWinFunctionTargetContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitColumnExprTrim(HogQLParser::ColumnExprTrimContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitColumnExprTuple(HogQLParser::ColumnExprTupleContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitColumnExprArrayAccess(HogQLParser::ColumnExprArrayAccessContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitColumnExprBetween(HogQLParser::ColumnExprBetweenContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitColumnExprPropertyAccess(HogQLParser::ColumnExprPropertyAccessContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitColumnExprParens(HogQLParser::ColumnExprParensContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitColumnExprTimestamp(HogQLParser::ColumnExprTimestampContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitColumnExprNullish(HogQLParser::ColumnExprNullishContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitColumnExprAnd(HogQLParser::ColumnExprAndContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitColumnExprTupleAccess(HogQLParser::ColumnExprTupleAccessContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitColumnExprCase(HogQLParser::ColumnExprCaseContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitColumnExprDate(HogQLParser::ColumnExprDateContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitColumnExprNot(HogQLParser::ColumnExprNotContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitColumnExprWinFunction(HogQLParser::ColumnExprWinFunctionContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitColumnExprIdentifier(HogQLParser::ColumnExprIdentifierContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitColumnExprFunction(HogQLParser::ColumnExprFunctionContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitColumnExprAsterisk(HogQLParser::ColumnExprAsteriskContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitColumnArgList(HogQLParser::ColumnArgListContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitColumnArgExpr(HogQLParser::ColumnArgExprContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitColumnLambdaExpr(HogQLParser::ColumnLambdaExprContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitWithExprList(HogQLParser::WithExprListContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitWithExprSubquery(HogQLParser::WithExprSubqueryContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitWithExprColumn(HogQLParser::WithExprColumnContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitColumnIdentifier(HogQLParser::ColumnIdentifierContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitNestedIdentifier(HogQLParser::NestedIdentifierContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitTableExprIdentifier(HogQLParser::TableExprIdentifierContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitTableExprPlaceholder(HogQLParser::TableExprPlaceholderContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitTableExprSubquery(HogQLParser::TableExprSubqueryContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitTableExprAlias(HogQLParser::TableExprAliasContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitTableExprFunction(HogQLParser::TableExprFunctionContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitTableFunctionExpr(HogQLParser::TableFunctionExprContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitTableIdentifier(HogQLParser::TableIdentifierContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitTableArgList(HogQLParser::TableArgListContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitDatabaseIdentifier(HogQLParser::DatabaseIdentifierContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitFloatingLiteral(HogQLParser::FloatingLiteralContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitNumberLiteral(HogQLParser::NumberLiteralContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitLiteral(HogQLParser::LiteralContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitInterval(HogQLParser::IntervalContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitKeyword(HogQLParser::KeywordContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitKeywordForAlias(HogQLParser::KeywordForAliasContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitAlias(HogQLParser::AliasContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitIdentifier(HogQLParser::IdentifierContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitEnumValue(HogQLParser::EnumValueContext *ctx) override {
    return visitChildren(ctx);
  }


};

