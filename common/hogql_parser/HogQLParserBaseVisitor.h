
// Generated from HogQLParser.g4 by ANTLR 4.13.2

#pragma once


#include "antlr4-runtime.h"
#include "HogQLParserVisitor.h"


/**
 * This class provides an empty implementation of HogQLParserVisitor, which can be
 * extended to create a visitor which only needs to handle a subset of the available methods.
 */
class  HogQLParserBaseVisitor : public HogQLParserVisitor {
public:

  virtual std::any visitProgram(HogQLParser::ProgramContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitDeclaration(HogQLParser::DeclarationContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitExpression(HogQLParser::ExpressionContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitVarDecl(HogQLParser::VarDeclContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitIdentifierList(HogQLParser::IdentifierListContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitStatement(HogQLParser::StatementContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitReturnStmt(HogQLParser::ReturnStmtContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitThrowStmt(HogQLParser::ThrowStmtContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitCatchBlock(HogQLParser::CatchBlockContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitTryCatchStmt(HogQLParser::TryCatchStmtContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitIfStmt(HogQLParser::IfStmtContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitWhileStmt(HogQLParser::WhileStmtContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitForStmt(HogQLParser::ForStmtContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitForInStmt(HogQLParser::ForInStmtContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitFuncStmt(HogQLParser::FuncStmtContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitVarAssignment(HogQLParser::VarAssignmentContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitExprStmt(HogQLParser::ExprStmtContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitEmptyStmt(HogQLParser::EmptyStmtContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitBlock(HogQLParser::BlockContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitKvPair(HogQLParser::KvPairContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitKvPairList(HogQLParser::KvPairListContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitSelect(HogQLParser::SelectContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitSelectStmtWithParens(HogQLParser::SelectStmtWithParensContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitSubsequentSelectSetClause(HogQLParser::SubsequentSelectSetClauseContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitSelectSetStmt(HogQLParser::SelectSetStmtContext *ctx) override {
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

  virtual std::any visitLimitByClause(HogQLParser::LimitByClauseContext *ctx) override {
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

  virtual std::any visitLimitExpr(HogQLParser::LimitExprContext *ctx) override {
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

  virtual std::any visitColumnExprNegate(HogQLParser::ColumnExprNegateContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitColumnExprDict(HogQLParser::ColumnExprDictContext *ctx) override {
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

  virtual std::any visitColumnExprNullTupleAccess(HogQLParser::ColumnExprNullTupleAccessContext *ctx) override {
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

  virtual std::any visitColumnExprCallSelect(HogQLParser::ColumnExprCallSelectContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitColumnExprIsNull(HogQLParser::ColumnExprIsNullContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitColumnExprWinFunctionTarget(HogQLParser::ColumnExprWinFunctionTargetContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitColumnExprNullPropertyAccess(HogQLParser::ColumnExprNullPropertyAccessContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitColumnExprIntervalString(HogQLParser::ColumnExprIntervalStringContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitColumnExprTrim(HogQLParser::ColumnExprTrimContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitColumnExprTagElement(HogQLParser::ColumnExprTagElementContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitColumnExprTemplateString(HogQLParser::ColumnExprTemplateStringContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitColumnExprTuple(HogQLParser::ColumnExprTupleContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitColumnExprCall(HogQLParser::ColumnExprCallContext *ctx) override {
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

  virtual std::any visitColumnExprNullArrayAccess(HogQLParser::ColumnExprNullArrayAccessContext *ctx) override {
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

  virtual std::any visitColumnExprLambda(HogQLParser::ColumnExprLambdaContext *ctx) override {
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

  virtual std::any visitColumnLambdaExpr(HogQLParser::ColumnLambdaExprContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitHogqlxChildElement(HogQLParser::HogqlxChildElementContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitHogqlxText(HogQLParser::HogqlxTextContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitHogqlxTagElementClosed(HogQLParser::HogqlxTagElementClosedContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitHogqlxTagElementNested(HogQLParser::HogqlxTagElementNestedContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitHogqlxTagAttribute(HogQLParser::HogqlxTagAttributeContext *ctx) override {
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

  virtual std::any visitTableExprTag(HogQLParser::TableExprTagContext *ctx) override {
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

  virtual std::any visitPlaceholder(HogQLParser::PlaceholderContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitString(HogQLParser::StringContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitTemplateString(HogQLParser::TemplateStringContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitStringContents(HogQLParser::StringContentsContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitFullTemplateString(HogQLParser::FullTemplateStringContext *ctx) override {
    return visitChildren(ctx);
  }

  virtual std::any visitStringContentsFull(HogQLParser::StringContentsFullContext *ctx) override {
    return visitChildren(ctx);
  }


};

