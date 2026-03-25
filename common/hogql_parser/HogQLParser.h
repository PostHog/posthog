
// Generated from HogQLParser.g4 by ANTLR 4.13.2

#pragma once


#include "antlr4-runtime.h"




class  HogQLParser : public antlr4::Parser {
public:
  enum {
    ALL = 1, AND = 2, ANTI = 3, ANY = 4, ARRAY = 5, AS = 6, ASCENDING = 7, 
    ASOF = 8, BETWEEN = 9, BOTH = 10, BY = 11, CASE = 12, CAST = 13, CATCH = 14, 
    COHORT = 15, COLLATE = 16, COLUMNS = 17, CROSS = 18, CUBE = 19, CURRENT = 20, 
    DATE = 21, DAY = 22, DESC = 23, DESCENDING = 24, DISTINCT = 25, ELSE = 26, 
    END = 27, EXCEPT = 28, EXCLUDE = 29, EXTRACT = 30, FINAL = 31, FILTER = 32, 
    FINALLY = 33, FIRST = 34, FN = 35, FOLLOWING = 36, FOR = 37, FROM = 38, 
    FULL = 39, FUN = 40, GROUP = 41, GROUPING = 42, HAVING = 43, HOUR = 44, 
    ID = 45, IF = 46, ILIKE = 47, IGNORE = 48, INCLUDE = 49, IN = 50, INF = 51, 
    INNER = 52, INTERSECT = 53, INTERVAL = 54, IS = 55, JOIN = 56, KEY = 57, 
    LAMBDA = 58, LAST = 59, LEADING = 60, LEFT = 61, LET = 62, LIKE = 63, 
    LIMIT = 64, MATERIALIZED = 65, MINUTE = 66, MONTH = 67, NAME = 68, NATURAL = 69, 
    NAN_SQL = 70, NOT = 71, NULL_SQL = 72, NULLS = 73, OFFSET = 74, ON = 75, 
    OR = 76, ORDER = 77, OUTER = 78, OVER = 79, PARTITION = 80, PIVOT = 81, 
    POSITIONAL = 82, PRECEDING = 83, PREWHERE = 84, QUALIFY = 85, QUARTER = 86, 
    RANGE = 87, RECURSIVE = 88, REPLACE = 89, RETURN = 90, RIGHT = 91, ROLLUP = 92, 
    ROW = 93, ROWS = 94, SAMPLE = 95, SECOND = 96, SELECT = 97, SEMI = 98, 
    SETS = 99, SETTINGS = 100, SUBSTRING = 101, THEN = 102, THROW = 103, 
    TIES = 104, TIMESTAMP = 105, TO = 106, TOP = 107, TOTALS = 108, TRAILING = 109, 
    TRIM = 110, TRUNCATE = 111, TRY = 112, TRY_CAST = 113, UNBOUNDED = 114, 
    UNION = 115, UNPIVOT = 116, USING = 117, VALUES = 118, WEEK = 119, WHEN = 120, 
    WHERE = 121, WHILE = 122, WINDOW = 123, WITH = 124, WITHIN = 125, YEAR = 126, 
    ESCAPE_CHAR_COMMON = 127, IDENTIFIER = 128, FLOATING_LITERAL = 129, 
    OCTAL_LITERAL = 130, DECIMAL_LITERAL = 131, HEXADECIMAL_LITERAL = 132, 
    STRING_LITERAL = 133, ARROW = 134, ASTERISK = 135, BACKQUOTE = 136, 
    BACKSLASH = 137, DOUBLECOLON = 138, COLONEQUALS = 139, COLON = 140, 
    COMMA = 141, CONCAT = 142, DASH = 143, DOLLAR = 144, DOT = 145, EQ_DOUBLE = 146, 
    EQ_SINGLE = 147, GT_EQ = 148, GT = 149, HASH = 150, IREGEX_SINGLE = 151, 
    IREGEX_DOUBLE = 152, LBRACE = 153, LBRACKET = 154, LPAREN = 155, LT_EQ = 156, 
    LT = 157, LT_SLASH = 158, NOT_EQ = 159, NOT_IREGEX = 160, NOT_REGEX = 161, 
    NULL_PROPERTY = 162, NULLISH = 163, PERCENT = 164, PLUS = 165, QUERY = 166, 
    QUOTE_DOUBLE = 167, QUOTE_SINGLE_TEMPLATE = 168, QUOTE_SINGLE_TEMPLATE_FULL = 169, 
    QUOTE_SINGLE = 170, REGEX_SINGLE = 171, REGEX_DOUBLE = 172, RBRACE = 173, 
    RBRACKET = 174, RPAREN = 175, SEMICOLON = 176, SLASH = 177, SLASH_GT = 178, 
    UNDERSCORE = 179, MULTI_LINE_COMMENT = 180, SINGLE_LINE_COMMENT = 181, 
    WHITESPACE = 182, STRING_TEXT = 183, STRING_ESCAPE_TRIGGER = 184, FULL_STRING_TEXT = 185, 
    FULL_STRING_ESCAPE_TRIGGER = 186, TAG_WS = 187, TAGC_WS = 188, HOGQLX_TEXT_TEXT = 189, 
    HOGQLX_TEXT_WS = 190
  };

  enum {
    RuleProgram = 0, RuleDeclaration = 1, RuleExpression = 2, RuleVarDecl = 3, 
    RuleIdentifierList = 4, RuleStatement = 5, RuleReturnStmt = 6, RuleThrowStmt = 7, 
    RuleCatchBlock = 8, RuleTryCatchStmt = 9, RuleIfStmt = 10, RuleWhileStmt = 11, 
    RuleForStmt = 12, RuleForInStmt = 13, RuleFuncStmt = 14, RuleVarAssignment = 15, 
    RuleExprStmt = 16, RuleEmptyStmt = 17, RuleBlock = 18, RuleKvPair = 19, 
    RuleKvPairList = 20, RuleSelect = 21, RuleSelectStmtWithParens = 22, 
    RuleSubsequentSelectSetClause = 23, RuleSelectSetStmt = 24, RuleLimitAndOffsetClauseOptional = 25, 
    RuleSelectStmt = 26, RuleWithClause = 27, RuleTopClause = 28, RuleFromClause = 29, 
    RuleArrayJoinClause = 30, RuleWindowClause = 31, RulePrewhereClause = 32, 
    RuleWhereClause = 33, RuleGroupByClause = 34, RuleGroupingSetList = 35, 
    RuleGroupingSet = 36, RuleHavingClause = 37, RuleQualifyClause = 38, 
    RuleOrderByClause = 39, RuleProjectionOrderByClause = 40, RuleLimitByClause = 41, 
    RuleLimitAndOffsetClause = 42, RuleOffsetOnlyClause = 43, RuleSettingsClause = 44, 
    RuleValuesClause = 45, RuleValuesRow = 46, RuleJoinExpr = 47, RuleJoinOp = 48, 
    RuleJoinOpCross = 49, RuleJoinConstraintClause = 50, RuleSampleClause = 51, 
    RuleLimitExpr = 52, RuleOrderExprList = 53, RuleOrderExpr = 54, RuleRatioExpr = 55, 
    RuleSettingExprList = 56, RuleSettingExpr = 57, RuleWindowExpr = 58, 
    RuleWinPartitionByClause = 59, RuleWinOrderByClause = 60, RuleWithinGroupClause = 61, 
    RuleWinFrameClause = 62, RuleWinFrameExtend = 63, RuleWinFrameBound = 64, 
    RuleExpr = 65, RuleColumnTypeExpr = 66, RuleColumnTypeCastExpr = 67, 
    RuleColumnExprList = 68, RuleSelectColumnExprList = 69, RuleSelectColumnExpr = 70, 
    RuleColumnExpr = 71, RuleColumnLambdaExpr = 72, RuleColumnsReplaceList = 73, 
    RuleColumnsReplaceItem = 74, RuleHogqlxChildElement = 75, RuleHogqlxText = 76, 
    RuleHogqlxTagElement = 77, RuleHogqlxTagAttribute = 78, RuleWithExprList = 79, 
    RuleWithExpr = 80, RuleWithExprColumnNameList = 81, RuleColumnIdentifier = 82, 
    RuleNestedIdentifier = 83, RuleTableExpr = 84, RulePivotColumnList = 85, 
    RulePivotColumn = 86, RuleUnpivotColumnList = 87, RuleUnpivotColumn = 88, 
    RuleColumnExprTupleOrSingle = 89, RuleColumnAliases = 90, RuleTableFunctionExpr = 91, 
    RuleTableIdentifier = 92, RuleTableArgList = 93, RuleDatabaseIdentifier = 94, 
    RuleFloatingLiteral = 95, RuleNumberLiteral = 96, RuleLiteral = 97, 
    RuleInterval = 98, RuleKeyword = 99, RuleKeywordForAlias = 100, RuleAlias = 101, 
    RuleIdentifier = 102, RuleEnumValue = 103, RulePlaceholder = 104, RuleString = 105, 
    RuleTemplateString = 106, RuleStringContents = 107, RuleFullTemplateString = 108, 
    RuleStringContentsFull = 109
  };

  explicit HogQLParser(antlr4::TokenStream *input);

  HogQLParser(antlr4::TokenStream *input, const antlr4::atn::ParserATNSimulatorOptions &options);

  ~HogQLParser() override;

  std::string getGrammarFileName() const override;

  const antlr4::atn::ATN& getATN() const override;

  const std::vector<std::string>& getRuleNames() const override;

  const antlr4::dfa::Vocabulary& getVocabulary() const override;

  antlr4::atn::SerializedATNView getSerializedATN() const override;


  class ProgramContext;
  class DeclarationContext;
  class ExpressionContext;
  class VarDeclContext;
  class IdentifierListContext;
  class StatementContext;
  class ReturnStmtContext;
  class ThrowStmtContext;
  class CatchBlockContext;
  class TryCatchStmtContext;
  class IfStmtContext;
  class WhileStmtContext;
  class ForStmtContext;
  class ForInStmtContext;
  class FuncStmtContext;
  class VarAssignmentContext;
  class ExprStmtContext;
  class EmptyStmtContext;
  class BlockContext;
  class KvPairContext;
  class KvPairListContext;
  class SelectContext;
  class SelectStmtWithParensContext;
  class SubsequentSelectSetClauseContext;
  class SelectSetStmtContext;
  class LimitAndOffsetClauseOptionalContext;
  class SelectStmtContext;
  class WithClauseContext;
  class TopClauseContext;
  class FromClauseContext;
  class ArrayJoinClauseContext;
  class WindowClauseContext;
  class PrewhereClauseContext;
  class WhereClauseContext;
  class GroupByClauseContext;
  class GroupingSetListContext;
  class GroupingSetContext;
  class HavingClauseContext;
  class QualifyClauseContext;
  class OrderByClauseContext;
  class ProjectionOrderByClauseContext;
  class LimitByClauseContext;
  class LimitAndOffsetClauseContext;
  class OffsetOnlyClauseContext;
  class SettingsClauseContext;
  class ValuesClauseContext;
  class ValuesRowContext;
  class JoinExprContext;
  class JoinOpContext;
  class JoinOpCrossContext;
  class JoinConstraintClauseContext;
  class SampleClauseContext;
  class LimitExprContext;
  class OrderExprListContext;
  class OrderExprContext;
  class RatioExprContext;
  class SettingExprListContext;
  class SettingExprContext;
  class WindowExprContext;
  class WinPartitionByClauseContext;
  class WinOrderByClauseContext;
  class WithinGroupClauseContext;
  class WinFrameClauseContext;
  class WinFrameExtendContext;
  class WinFrameBoundContext;
  class ExprContext;
  class ColumnTypeExprContext;
  class ColumnTypeCastExprContext;
  class ColumnExprListContext;
  class SelectColumnExprListContext;
  class SelectColumnExprContext;
  class ColumnExprContext;
  class ColumnLambdaExprContext;
  class ColumnsReplaceListContext;
  class ColumnsReplaceItemContext;
  class HogqlxChildElementContext;
  class HogqlxTextContext;
  class HogqlxTagElementContext;
  class HogqlxTagAttributeContext;
  class WithExprListContext;
  class WithExprContext;
  class WithExprColumnNameListContext;
  class ColumnIdentifierContext;
  class NestedIdentifierContext;
  class TableExprContext;
  class PivotColumnListContext;
  class PivotColumnContext;
  class UnpivotColumnListContext;
  class UnpivotColumnContext;
  class ColumnExprTupleOrSingleContext;
  class ColumnAliasesContext;
  class TableFunctionExprContext;
  class TableIdentifierContext;
  class TableArgListContext;
  class DatabaseIdentifierContext;
  class FloatingLiteralContext;
  class NumberLiteralContext;
  class LiteralContext;
  class IntervalContext;
  class KeywordContext;
  class KeywordForAliasContext;
  class AliasContext;
  class IdentifierContext;
  class EnumValueContext;
  class PlaceholderContext;
  class StringContext;
  class TemplateStringContext;
  class StringContentsContext;
  class FullTemplateStringContext;
  class StringContentsFullContext; 

  class  ProgramContext : public antlr4::ParserRuleContext {
  public:
    ProgramContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *EOF();
    std::vector<DeclarationContext *> declaration();
    DeclarationContext* declaration(size_t i);


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  ProgramContext* program();

  class  DeclarationContext : public antlr4::ParserRuleContext {
  public:
    DeclarationContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    VarDeclContext *varDecl();
    StatementContext *statement();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  DeclarationContext* declaration();

  class  ExpressionContext : public antlr4::ParserRuleContext {
  public:
    ExpressionContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    ColumnExprContext *columnExpr();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  ExpressionContext* expression();

  class  VarDeclContext : public antlr4::ParserRuleContext {
  public:
    VarDeclContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *LET();
    IdentifierContext *identifier();
    antlr4::tree::TerminalNode *COLONEQUALS();
    ExpressionContext *expression();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  VarDeclContext* varDecl();

  class  IdentifierListContext : public antlr4::ParserRuleContext {
  public:
    IdentifierListContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    std::vector<NestedIdentifierContext *> nestedIdentifier();
    NestedIdentifierContext* nestedIdentifier(size_t i);
    std::vector<antlr4::tree::TerminalNode *> COMMA();
    antlr4::tree::TerminalNode* COMMA(size_t i);


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  IdentifierListContext* identifierList();

  class  StatementContext : public antlr4::ParserRuleContext {
  public:
    StatementContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    ReturnStmtContext *returnStmt();
    ThrowStmtContext *throwStmt();
    TryCatchStmtContext *tryCatchStmt();
    IfStmtContext *ifStmt();
    WhileStmtContext *whileStmt();
    ForInStmtContext *forInStmt();
    ForStmtContext *forStmt();
    FuncStmtContext *funcStmt();
    VarAssignmentContext *varAssignment();
    BlockContext *block();
    ExprStmtContext *exprStmt();
    EmptyStmtContext *emptyStmt();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  StatementContext* statement();

  class  ReturnStmtContext : public antlr4::ParserRuleContext {
  public:
    ReturnStmtContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *RETURN();
    ExpressionContext *expression();
    antlr4::tree::TerminalNode *SEMICOLON();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  ReturnStmtContext* returnStmt();

  class  ThrowStmtContext : public antlr4::ParserRuleContext {
  public:
    ThrowStmtContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *THROW();
    ExpressionContext *expression();
    antlr4::tree::TerminalNode *SEMICOLON();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  ThrowStmtContext* throwStmt();

  class  CatchBlockContext : public antlr4::ParserRuleContext {
  public:
    HogQLParser::IdentifierContext *catchVar = nullptr;
    HogQLParser::IdentifierContext *catchType = nullptr;
    HogQLParser::BlockContext *catchStmt = nullptr;
    CatchBlockContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *CATCH();
    BlockContext *block();
    antlr4::tree::TerminalNode *LPAREN();
    antlr4::tree::TerminalNode *RPAREN();
    std::vector<IdentifierContext *> identifier();
    IdentifierContext* identifier(size_t i);
    antlr4::tree::TerminalNode *COLON();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  CatchBlockContext* catchBlock();

  class  TryCatchStmtContext : public antlr4::ParserRuleContext {
  public:
    HogQLParser::BlockContext *tryStmt = nullptr;
    HogQLParser::BlockContext *finallyStmt = nullptr;
    TryCatchStmtContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *TRY();
    std::vector<BlockContext *> block();
    BlockContext* block(size_t i);
    std::vector<CatchBlockContext *> catchBlock();
    CatchBlockContext* catchBlock(size_t i);
    antlr4::tree::TerminalNode *FINALLY();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  TryCatchStmtContext* tryCatchStmt();

  class  IfStmtContext : public antlr4::ParserRuleContext {
  public:
    IfStmtContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *IF();
    antlr4::tree::TerminalNode *LPAREN();
    ExpressionContext *expression();
    antlr4::tree::TerminalNode *RPAREN();
    std::vector<StatementContext *> statement();
    StatementContext* statement(size_t i);
    antlr4::tree::TerminalNode *ELSE();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  IfStmtContext* ifStmt();

  class  WhileStmtContext : public antlr4::ParserRuleContext {
  public:
    WhileStmtContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *WHILE();
    antlr4::tree::TerminalNode *LPAREN();
    ExpressionContext *expression();
    antlr4::tree::TerminalNode *RPAREN();
    StatementContext *statement();
    antlr4::tree::TerminalNode *SEMICOLON();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  WhileStmtContext* whileStmt();

  class  ForStmtContext : public antlr4::ParserRuleContext {
  public:
    HogQLParser::VarDeclContext *initializerVarDeclr = nullptr;
    HogQLParser::VarAssignmentContext *initializerVarAssignment = nullptr;
    HogQLParser::ExpressionContext *initializerExpression = nullptr;
    HogQLParser::ExpressionContext *condition = nullptr;
    HogQLParser::VarDeclContext *incrementVarDeclr = nullptr;
    HogQLParser::VarAssignmentContext *incrementVarAssignment = nullptr;
    HogQLParser::ExpressionContext *incrementExpression = nullptr;
    ForStmtContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *FOR();
    antlr4::tree::TerminalNode *LPAREN();
    std::vector<antlr4::tree::TerminalNode *> SEMICOLON();
    antlr4::tree::TerminalNode* SEMICOLON(size_t i);
    antlr4::tree::TerminalNode *RPAREN();
    StatementContext *statement();
    std::vector<VarDeclContext *> varDecl();
    VarDeclContext* varDecl(size_t i);
    std::vector<VarAssignmentContext *> varAssignment();
    VarAssignmentContext* varAssignment(size_t i);
    std::vector<ExpressionContext *> expression();
    ExpressionContext* expression(size_t i);


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  ForStmtContext* forStmt();

  class  ForInStmtContext : public antlr4::ParserRuleContext {
  public:
    ForInStmtContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *FOR();
    antlr4::tree::TerminalNode *LPAREN();
    antlr4::tree::TerminalNode *LET();
    std::vector<IdentifierContext *> identifier();
    IdentifierContext* identifier(size_t i);
    antlr4::tree::TerminalNode *IN();
    ExpressionContext *expression();
    antlr4::tree::TerminalNode *RPAREN();
    StatementContext *statement();
    antlr4::tree::TerminalNode *COMMA();
    antlr4::tree::TerminalNode *SEMICOLON();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  ForInStmtContext* forInStmt();

  class  FuncStmtContext : public antlr4::ParserRuleContext {
  public:
    FuncStmtContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    IdentifierContext *identifier();
    antlr4::tree::TerminalNode *LPAREN();
    antlr4::tree::TerminalNode *RPAREN();
    BlockContext *block();
    antlr4::tree::TerminalNode *FN();
    antlr4::tree::TerminalNode *FUN();
    IdentifierListContext *identifierList();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  FuncStmtContext* funcStmt();

  class  VarAssignmentContext : public antlr4::ParserRuleContext {
  public:
    VarAssignmentContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    std::vector<ExpressionContext *> expression();
    ExpressionContext* expression(size_t i);
    antlr4::tree::TerminalNode *COLONEQUALS();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  VarAssignmentContext* varAssignment();

  class  ExprStmtContext : public antlr4::ParserRuleContext {
  public:
    ExprStmtContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    ExpressionContext *expression();
    antlr4::tree::TerminalNode *SEMICOLON();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  ExprStmtContext* exprStmt();

  class  EmptyStmtContext : public antlr4::ParserRuleContext {
  public:
    EmptyStmtContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *SEMICOLON();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  EmptyStmtContext* emptyStmt();

  class  BlockContext : public antlr4::ParserRuleContext {
  public:
    BlockContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *LBRACE();
    antlr4::tree::TerminalNode *RBRACE();
    std::vector<DeclarationContext *> declaration();
    DeclarationContext* declaration(size_t i);


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  BlockContext* block();

  class  KvPairContext : public antlr4::ParserRuleContext {
  public:
    KvPairContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    std::vector<ExpressionContext *> expression();
    ExpressionContext* expression(size_t i);
    antlr4::tree::TerminalNode *COLON();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  KvPairContext* kvPair();

  class  KvPairListContext : public antlr4::ParserRuleContext {
  public:
    KvPairListContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    std::vector<KvPairContext *> kvPair();
    KvPairContext* kvPair(size_t i);
    std::vector<antlr4::tree::TerminalNode *> COMMA();
    antlr4::tree::TerminalNode* COMMA(size_t i);


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  KvPairListContext* kvPairList();

  class  SelectContext : public antlr4::ParserRuleContext {
  public:
    SelectContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *EOF();
    SelectSetStmtContext *selectSetStmt();
    SelectStmtContext *selectStmt();
    HogqlxTagElementContext *hogqlxTagElement();
    antlr4::tree::TerminalNode *SEMICOLON();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  SelectContext* select();

  class  SelectStmtWithParensContext : public antlr4::ParserRuleContext {
  public:
    SelectStmtWithParensContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    SelectStmtContext *selectStmt();
    WithClauseContext *withClause();
    antlr4::tree::TerminalNode *LPAREN();
    SelectSetStmtContext *selectSetStmt();
    antlr4::tree::TerminalNode *RPAREN();
    PlaceholderContext *placeholder();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  SelectStmtWithParensContext* selectStmtWithParens();

  class  SubsequentSelectSetClauseContext : public antlr4::ParserRuleContext {
  public:
    SubsequentSelectSetClauseContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    SelectStmtWithParensContext *selectStmtWithParens();
    antlr4::tree::TerminalNode *EXCEPT();
    antlr4::tree::TerminalNode *ALL();
    antlr4::tree::TerminalNode *UNION();
    antlr4::tree::TerminalNode *DISTINCT();
    antlr4::tree::TerminalNode *INTERSECT();
    antlr4::tree::TerminalNode *BY();
    antlr4::tree::TerminalNode *NAME();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  SubsequentSelectSetClauseContext* subsequentSelectSetClause();

  class  SelectSetStmtContext : public antlr4::ParserRuleContext {
  public:
    SelectSetStmtContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    SelectStmtWithParensContext *selectStmtWithParens();
    std::vector<SubsequentSelectSetClauseContext *> subsequentSelectSetClause();
    SubsequentSelectSetClauseContext* subsequentSelectSetClause(size_t i);
    OrderByClauseContext *orderByClause();
    LimitAndOffsetClauseOptionalContext *limitAndOffsetClauseOptional();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  SelectSetStmtContext* selectSetStmt();

  class  LimitAndOffsetClauseOptionalContext : public antlr4::ParserRuleContext {
  public:
    LimitAndOffsetClauseOptionalContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *LIMIT();
    std::vector<ColumnExprContext *> columnExpr();
    ColumnExprContext* columnExpr(size_t i);
    antlr4::tree::TerminalNode *PERCENT();
    antlr4::tree::TerminalNode *COMMA();
    antlr4::tree::TerminalNode *WITH();
    antlr4::tree::TerminalNode *TIES();
    antlr4::tree::TerminalNode *OFFSET();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  LimitAndOffsetClauseOptionalContext* limitAndOffsetClauseOptional();

  class  SelectStmtContext : public antlr4::ParserRuleContext {
  public:
    HogQLParser::WithClauseContext *with = nullptr;
    HogQLParser::SelectColumnExprListContext *columns = nullptr;
    HogQLParser::FromClauseContext *from = nullptr;
    HogQLParser::WhereClauseContext *where = nullptr;
    SelectStmtContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *SELECT();
    SelectColumnExprListContext *selectColumnExprList();
    antlr4::tree::TerminalNode *DISTINCT();
    TopClauseContext *topClause();
    ArrayJoinClauseContext *arrayJoinClause();
    PrewhereClauseContext *prewhereClause();
    std::vector<SampleClauseContext *> sampleClause();
    SampleClauseContext* sampleClause(size_t i);
    GroupByClauseContext *groupByClause();
    std::vector<antlr4::tree::TerminalNode *> WITH();
    antlr4::tree::TerminalNode* WITH(size_t i);
    antlr4::tree::TerminalNode *TOTALS();
    HavingClauseContext *havingClause();
    QualifyClauseContext *qualifyClause();
    std::vector<antlr4::tree::TerminalNode *> USING();
    antlr4::tree::TerminalNode* USING(size_t i);
    WindowClauseContext *windowClause();
    OrderByClauseContext *orderByClause();
    LimitByClauseContext *limitByClause();
    LimitAndOffsetClauseContext *limitAndOffsetClause();
    OffsetOnlyClauseContext *offsetOnlyClause();
    SettingsClauseContext *settingsClause();
    WithClauseContext *withClause();
    FromClauseContext *fromClause();
    WhereClauseContext *whereClause();
    antlr4::tree::TerminalNode *CUBE();
    antlr4::tree::TerminalNode *ROLLUP();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  SelectStmtContext* selectStmt();

  class  WithClauseContext : public antlr4::ParserRuleContext {
  public:
    WithClauseContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *WITH();
    WithExprListContext *withExprList();
    antlr4::tree::TerminalNode *RECURSIVE();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  WithClauseContext* withClause();

  class  TopClauseContext : public antlr4::ParserRuleContext {
  public:
    TopClauseContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *TOP();
    antlr4::tree::TerminalNode *DECIMAL_LITERAL();
    antlr4::tree::TerminalNode *WITH();
    antlr4::tree::TerminalNode *TIES();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  TopClauseContext* topClause();

  class  FromClauseContext : public antlr4::ParserRuleContext {
  public:
    FromClauseContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *FROM();
    JoinExprContext *joinExpr();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  FromClauseContext* fromClause();

  class  ArrayJoinClauseContext : public antlr4::ParserRuleContext {
  public:
    ArrayJoinClauseContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *ARRAY();
    antlr4::tree::TerminalNode *JOIN();
    ColumnExprListContext *columnExprList();
    antlr4::tree::TerminalNode *LEFT();
    antlr4::tree::TerminalNode *INNER();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  ArrayJoinClauseContext* arrayJoinClause();

  class  WindowClauseContext : public antlr4::ParserRuleContext {
  public:
    WindowClauseContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *WINDOW();
    std::vector<IdentifierContext *> identifier();
    IdentifierContext* identifier(size_t i);
    std::vector<antlr4::tree::TerminalNode *> AS();
    antlr4::tree::TerminalNode* AS(size_t i);
    std::vector<antlr4::tree::TerminalNode *> LPAREN();
    antlr4::tree::TerminalNode* LPAREN(size_t i);
    std::vector<WindowExprContext *> windowExpr();
    WindowExprContext* windowExpr(size_t i);
    std::vector<antlr4::tree::TerminalNode *> RPAREN();
    antlr4::tree::TerminalNode* RPAREN(size_t i);
    std::vector<antlr4::tree::TerminalNode *> COMMA();
    antlr4::tree::TerminalNode* COMMA(size_t i);


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  WindowClauseContext* windowClause();

  class  PrewhereClauseContext : public antlr4::ParserRuleContext {
  public:
    PrewhereClauseContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *PREWHERE();
    ColumnExprContext *columnExpr();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  PrewhereClauseContext* prewhereClause();

  class  WhereClauseContext : public antlr4::ParserRuleContext {
  public:
    WhereClauseContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *WHERE();
    ColumnExprContext *columnExpr();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  WhereClauseContext* whereClause();

  class  GroupByClauseContext : public antlr4::ParserRuleContext {
  public:
    GroupByClauseContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *GROUP();
    antlr4::tree::TerminalNode *BY();
    antlr4::tree::TerminalNode *ALL();
    antlr4::tree::TerminalNode *LPAREN();
    ColumnExprListContext *columnExprList();
    antlr4::tree::TerminalNode *RPAREN();
    antlr4::tree::TerminalNode *GROUPING();
    antlr4::tree::TerminalNode *SETS();
    GroupingSetListContext *groupingSetList();
    antlr4::tree::TerminalNode *CUBE();
    antlr4::tree::TerminalNode *ROLLUP();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  GroupByClauseContext* groupByClause();

  class  GroupingSetListContext : public antlr4::ParserRuleContext {
  public:
    GroupingSetListContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    std::vector<GroupingSetContext *> groupingSet();
    GroupingSetContext* groupingSet(size_t i);
    std::vector<antlr4::tree::TerminalNode *> COMMA();
    antlr4::tree::TerminalNode* COMMA(size_t i);


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  GroupingSetListContext* groupingSetList();

  class  GroupingSetContext : public antlr4::ParserRuleContext {
  public:
    GroupingSetContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *LPAREN();
    antlr4::tree::TerminalNode *RPAREN();
    ColumnExprListContext *columnExprList();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  GroupingSetContext* groupingSet();

  class  HavingClauseContext : public antlr4::ParserRuleContext {
  public:
    HavingClauseContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *HAVING();
    ColumnExprContext *columnExpr();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  HavingClauseContext* havingClause();

  class  QualifyClauseContext : public antlr4::ParserRuleContext {
  public:
    QualifyClauseContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *QUALIFY();
    ColumnExprContext *columnExpr();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  QualifyClauseContext* qualifyClause();

  class  OrderByClauseContext : public antlr4::ParserRuleContext {
  public:
    OrderByClauseContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *ORDER();
    antlr4::tree::TerminalNode *BY();
    OrderExprListContext *orderExprList();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  OrderByClauseContext* orderByClause();

  class  ProjectionOrderByClauseContext : public antlr4::ParserRuleContext {
  public:
    ProjectionOrderByClauseContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *ORDER();
    antlr4::tree::TerminalNode *BY();
    ColumnExprListContext *columnExprList();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  ProjectionOrderByClauseContext* projectionOrderByClause();

  class  LimitByClauseContext : public antlr4::ParserRuleContext {
  public:
    LimitByClauseContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *LIMIT();
    LimitExprContext *limitExpr();
    antlr4::tree::TerminalNode *BY();
    ColumnExprListContext *columnExprList();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  LimitByClauseContext* limitByClause();

  class  LimitAndOffsetClauseContext : public antlr4::ParserRuleContext {
  public:
    LimitAndOffsetClauseContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *LIMIT();
    std::vector<ColumnExprContext *> columnExpr();
    ColumnExprContext* columnExpr(size_t i);
    antlr4::tree::TerminalNode *PERCENT();
    antlr4::tree::TerminalNode *COMMA();
    antlr4::tree::TerminalNode *WITH();
    antlr4::tree::TerminalNode *TIES();
    antlr4::tree::TerminalNode *OFFSET();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  LimitAndOffsetClauseContext* limitAndOffsetClause();

  class  OffsetOnlyClauseContext : public antlr4::ParserRuleContext {
  public:
    OffsetOnlyClauseContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *OFFSET();
    ColumnExprContext *columnExpr();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  OffsetOnlyClauseContext* offsetOnlyClause();

  class  SettingsClauseContext : public antlr4::ParserRuleContext {
  public:
    SettingsClauseContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *SETTINGS();
    SettingExprListContext *settingExprList();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  SettingsClauseContext* settingsClause();

  class  ValuesClauseContext : public antlr4::ParserRuleContext {
  public:
    ValuesClauseContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *VALUES();
    std::vector<ValuesRowContext *> valuesRow();
    ValuesRowContext* valuesRow(size_t i);
    std::vector<antlr4::tree::TerminalNode *> COMMA();
    antlr4::tree::TerminalNode* COMMA(size_t i);


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  ValuesClauseContext* valuesClause();

  class  ValuesRowContext : public antlr4::ParserRuleContext {
  public:
    ValuesRowContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *LPAREN();
    std::vector<ColumnExprContext *> columnExpr();
    ColumnExprContext* columnExpr(size_t i);
    antlr4::tree::TerminalNode *RPAREN();
    std::vector<antlr4::tree::TerminalNode *> COMMA();
    antlr4::tree::TerminalNode* COMMA(size_t i);


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  ValuesRowContext* valuesRow();

  class  JoinExprContext : public antlr4::ParserRuleContext {
  public:
    JoinExprContext(antlr4::ParserRuleContext *parent, size_t invokingState);
   
    JoinExprContext() = default;
    void copyFrom(JoinExprContext *context);
    using antlr4::ParserRuleContext::copyFrom;

    virtual size_t getRuleIndex() const override;

   
  };

  class  JoinExprPositionalContext : public JoinExprContext {
  public:
    JoinExprPositionalContext(JoinExprContext *ctx);

    std::vector<JoinExprContext *> joinExpr();
    JoinExprContext* joinExpr(size_t i);
    antlr4::tree::TerminalNode *POSITIONAL();
    antlr4::tree::TerminalNode *JOIN();
    JoinConstraintClauseContext *joinConstraintClause();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  JoinExprOpContext : public JoinExprContext {
  public:
    JoinExprOpContext(JoinExprContext *ctx);

    std::vector<JoinExprContext *> joinExpr();
    JoinExprContext* joinExpr(size_t i);
    antlr4::tree::TerminalNode *JOIN();
    antlr4::tree::TerminalNode *NATURAL();
    JoinOpContext *joinOp();
    JoinConstraintClauseContext *joinConstraintClause();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  JoinExprTableContext : public JoinExprContext {
  public:
    JoinExprTableContext(JoinExprContext *ctx);

    TableExprContext *tableExpr();
    antlr4::tree::TerminalNode *FINAL();
    SampleClauseContext *sampleClause();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  JoinExprUnpivotContext : public JoinExprContext {
  public:
    JoinExprUnpivotContext(JoinExprContext *ctx);

    JoinExprContext *joinExpr();
    antlr4::tree::TerminalNode *UNPIVOT();
    antlr4::tree::TerminalNode *LPAREN();
    UnpivotColumnListContext *unpivotColumnList();
    antlr4::tree::TerminalNode *RPAREN();
    antlr4::tree::TerminalNode *INCLUDE();
    antlr4::tree::TerminalNode *NULLS();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  JoinExprParensContext : public JoinExprContext {
  public:
    JoinExprParensContext(JoinExprContext *ctx);

    antlr4::tree::TerminalNode *LPAREN();
    JoinExprContext *joinExpr();
    antlr4::tree::TerminalNode *RPAREN();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  JoinExprCrossOpContext : public JoinExprContext {
  public:
    JoinExprCrossOpContext(JoinExprContext *ctx);

    std::vector<JoinExprContext *> joinExpr();
    JoinExprContext* joinExpr(size_t i);
    JoinOpCrossContext *joinOpCross();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  JoinExprPivotContext : public JoinExprContext {
  public:
    JoinExprPivotContext(JoinExprContext *ctx);

    JoinExprContext *joinExpr();
    antlr4::tree::TerminalNode *PIVOT();
    antlr4::tree::TerminalNode *LPAREN();
    std::vector<ColumnExprListContext *> columnExprList();
    ColumnExprListContext* columnExprList(size_t i);
    PivotColumnListContext *pivotColumnList();
    antlr4::tree::TerminalNode *RPAREN();
    antlr4::tree::TerminalNode *GROUP();
    antlr4::tree::TerminalNode *BY();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  JoinExprContext* joinExpr();
  JoinExprContext* joinExpr(int precedence);
  class  JoinOpContext : public antlr4::ParserRuleContext {
  public:
    JoinOpContext(antlr4::ParserRuleContext *parent, size_t invokingState);
   
    JoinOpContext() = default;
    void copyFrom(JoinOpContext *context);
    using antlr4::ParserRuleContext::copyFrom;

    virtual size_t getRuleIndex() const override;

   
  };

  class  JoinOpFullContext : public JoinOpContext {
  public:
    JoinOpFullContext(JoinOpContext *ctx);

    antlr4::tree::TerminalNode *FULL();
    antlr4::tree::TerminalNode *OUTER();
    antlr4::tree::TerminalNode *ALL();
    antlr4::tree::TerminalNode *ANY();
    antlr4::tree::TerminalNode *ASOF();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  JoinOpInnerContext : public JoinOpContext {
  public:
    JoinOpInnerContext(JoinOpContext *ctx);

    antlr4::tree::TerminalNode *INNER();
    antlr4::tree::TerminalNode *ANTI();
    antlr4::tree::TerminalNode *SEMI();
    antlr4::tree::TerminalNode *ASOF();
    antlr4::tree::TerminalNode *ALL();
    antlr4::tree::TerminalNode *ANY();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  JoinOpLeftRightContext : public JoinOpContext {
  public:
    JoinOpLeftRightContext(JoinOpContext *ctx);

    antlr4::tree::TerminalNode *ASOF();
    antlr4::tree::TerminalNode *LEFT();
    antlr4::tree::TerminalNode *RIGHT();
    antlr4::tree::TerminalNode *ANTI();
    antlr4::tree::TerminalNode *SEMI();
    antlr4::tree::TerminalNode *OUTER();
    antlr4::tree::TerminalNode *ALL();
    antlr4::tree::TerminalNode *ANY();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  JoinOpContext* joinOp();

  class  JoinOpCrossContext : public antlr4::ParserRuleContext {
  public:
    JoinOpCrossContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *CROSS();
    antlr4::tree::TerminalNode *JOIN();
    antlr4::tree::TerminalNode *COMMA();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  JoinOpCrossContext* joinOpCross();

  class  JoinConstraintClauseContext : public antlr4::ParserRuleContext {
  public:
    JoinConstraintClauseContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *ON();
    ColumnExprListContext *columnExprList();
    antlr4::tree::TerminalNode *USING();
    antlr4::tree::TerminalNode *LPAREN();
    antlr4::tree::TerminalNode *RPAREN();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  JoinConstraintClauseContext* joinConstraintClause();

  class  SampleClauseContext : public antlr4::ParserRuleContext {
  public:
    SampleClauseContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *SAMPLE();
    std::vector<RatioExprContext *> ratioExpr();
    RatioExprContext* ratioExpr(size_t i);
    antlr4::tree::TerminalNode *PERCENT();
    antlr4::tree::TerminalNode *OFFSET();
    antlr4::tree::TerminalNode *LPAREN();
    IdentifierContext *identifier();
    antlr4::tree::TerminalNode *RPAREN();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  SampleClauseContext* sampleClause();

  class  LimitExprContext : public antlr4::ParserRuleContext {
  public:
    LimitExprContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    std::vector<ColumnExprContext *> columnExpr();
    ColumnExprContext* columnExpr(size_t i);
    antlr4::tree::TerminalNode *COMMA();
    antlr4::tree::TerminalNode *OFFSET();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  LimitExprContext* limitExpr();

  class  OrderExprListContext : public antlr4::ParserRuleContext {
  public:
    OrderExprListContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    std::vector<OrderExprContext *> orderExpr();
    OrderExprContext* orderExpr(size_t i);
    std::vector<antlr4::tree::TerminalNode *> COMMA();
    antlr4::tree::TerminalNode* COMMA(size_t i);


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  OrderExprListContext* orderExprList();

  class  OrderExprContext : public antlr4::ParserRuleContext {
  public:
    OrderExprContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    ColumnExprContext *columnExpr();
    antlr4::tree::TerminalNode *NULLS();
    antlr4::tree::TerminalNode *COLLATE();
    antlr4::tree::TerminalNode *STRING_LITERAL();
    antlr4::tree::TerminalNode *ASCENDING();
    antlr4::tree::TerminalNode *DESCENDING();
    antlr4::tree::TerminalNode *DESC();
    antlr4::tree::TerminalNode *FIRST();
    antlr4::tree::TerminalNode *LAST();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  OrderExprContext* orderExpr();

  class  RatioExprContext : public antlr4::ParserRuleContext {
  public:
    RatioExprContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    PlaceholderContext *placeholder();
    std::vector<NumberLiteralContext *> numberLiteral();
    NumberLiteralContext* numberLiteral(size_t i);
    antlr4::tree::TerminalNode *SLASH();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  RatioExprContext* ratioExpr();

  class  SettingExprListContext : public antlr4::ParserRuleContext {
  public:
    SettingExprListContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    std::vector<SettingExprContext *> settingExpr();
    SettingExprContext* settingExpr(size_t i);
    std::vector<antlr4::tree::TerminalNode *> COMMA();
    antlr4::tree::TerminalNode* COMMA(size_t i);


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  SettingExprListContext* settingExprList();

  class  SettingExprContext : public antlr4::ParserRuleContext {
  public:
    SettingExprContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    IdentifierContext *identifier();
    antlr4::tree::TerminalNode *EQ_SINGLE();
    LiteralContext *literal();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  SettingExprContext* settingExpr();

  class  WindowExprContext : public antlr4::ParserRuleContext {
  public:
    WindowExprContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    WinPartitionByClauseContext *winPartitionByClause();
    WinOrderByClauseContext *winOrderByClause();
    WinFrameClauseContext *winFrameClause();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  WindowExprContext* windowExpr();

  class  WinPartitionByClauseContext : public antlr4::ParserRuleContext {
  public:
    WinPartitionByClauseContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *PARTITION();
    antlr4::tree::TerminalNode *BY();
    ColumnExprListContext *columnExprList();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  WinPartitionByClauseContext* winPartitionByClause();

  class  WinOrderByClauseContext : public antlr4::ParserRuleContext {
  public:
    WinOrderByClauseContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *ORDER();
    antlr4::tree::TerminalNode *BY();
    OrderExprListContext *orderExprList();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  WinOrderByClauseContext* winOrderByClause();

  class  WithinGroupClauseContext : public antlr4::ParserRuleContext {
  public:
    WithinGroupClauseContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *WITHIN();
    antlr4::tree::TerminalNode *GROUP();
    antlr4::tree::TerminalNode *LPAREN();
    OrderByClauseContext *orderByClause();
    antlr4::tree::TerminalNode *RPAREN();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  WithinGroupClauseContext* withinGroupClause();

  class  WinFrameClauseContext : public antlr4::ParserRuleContext {
  public:
    WinFrameClauseContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    WinFrameExtendContext *winFrameExtend();
    antlr4::tree::TerminalNode *ROWS();
    antlr4::tree::TerminalNode *RANGE();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  WinFrameClauseContext* winFrameClause();

  class  WinFrameExtendContext : public antlr4::ParserRuleContext {
  public:
    WinFrameExtendContext(antlr4::ParserRuleContext *parent, size_t invokingState);
   
    WinFrameExtendContext() = default;
    void copyFrom(WinFrameExtendContext *context);
    using antlr4::ParserRuleContext::copyFrom;

    virtual size_t getRuleIndex() const override;

   
  };

  class  FrameStartContext : public WinFrameExtendContext {
  public:
    FrameStartContext(WinFrameExtendContext *ctx);

    WinFrameBoundContext *winFrameBound();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  FrameBetweenContext : public WinFrameExtendContext {
  public:
    FrameBetweenContext(WinFrameExtendContext *ctx);

    antlr4::tree::TerminalNode *BETWEEN();
    std::vector<WinFrameBoundContext *> winFrameBound();
    WinFrameBoundContext* winFrameBound(size_t i);
    antlr4::tree::TerminalNode *AND();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  WinFrameExtendContext* winFrameExtend();

  class  WinFrameBoundContext : public antlr4::ParserRuleContext {
  public:
    WinFrameBoundContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *CURRENT();
    antlr4::tree::TerminalNode *ROW();
    antlr4::tree::TerminalNode *UNBOUNDED();
    antlr4::tree::TerminalNode *PRECEDING();
    antlr4::tree::TerminalNode *FOLLOWING();
    ColumnExprContext *columnExpr();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  WinFrameBoundContext* winFrameBound();

  class  ExprContext : public antlr4::ParserRuleContext {
  public:
    ExprContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    ColumnExprContext *columnExpr();
    antlr4::tree::TerminalNode *EOF();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  ExprContext* expr();

  class  ColumnTypeExprContext : public antlr4::ParserRuleContext {
  public:
    ColumnTypeExprContext(antlr4::ParserRuleContext *parent, size_t invokingState);
   
    ColumnTypeExprContext() = default;
    void copyFrom(ColumnTypeExprContext *context);
    using antlr4::ParserRuleContext::copyFrom;

    virtual size_t getRuleIndex() const override;

   
  };

  class  ColumnTypeExprNestedContext : public ColumnTypeExprContext {
  public:
    ColumnTypeExprNestedContext(ColumnTypeExprContext *ctx);

    std::vector<IdentifierContext *> identifier();
    IdentifierContext* identifier(size_t i);
    antlr4::tree::TerminalNode *LPAREN();
    std::vector<ColumnTypeExprContext *> columnTypeExpr();
    ColumnTypeExprContext* columnTypeExpr(size_t i);
    antlr4::tree::TerminalNode *RPAREN();
    std::vector<antlr4::tree::TerminalNode *> COMMA();
    antlr4::tree::TerminalNode* COMMA(size_t i);

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnTypeExprParamContext : public ColumnTypeExprContext {
  public:
    ColumnTypeExprParamContext(ColumnTypeExprContext *ctx);

    IdentifierContext *identifier();
    antlr4::tree::TerminalNode *LPAREN();
    antlr4::tree::TerminalNode *RPAREN();
    ColumnExprListContext *columnExprList();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnTypeExprArrayContext : public ColumnTypeExprContext {
  public:
    ColumnTypeExprArrayContext(ColumnTypeExprContext *ctx);

    ColumnTypeExprContext *columnTypeExpr();
    antlr4::tree::TerminalNode *LBRACKET();
    antlr4::tree::TerminalNode *RBRACKET();
    antlr4::tree::TerminalNode *DECIMAL_LITERAL();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnTypeExprComplexContext : public ColumnTypeExprContext {
  public:
    ColumnTypeExprComplexContext(ColumnTypeExprContext *ctx);

    IdentifierContext *identifier();
    antlr4::tree::TerminalNode *LPAREN();
    std::vector<ColumnTypeExprContext *> columnTypeExpr();
    ColumnTypeExprContext* columnTypeExpr(size_t i);
    antlr4::tree::TerminalNode *RPAREN();
    std::vector<antlr4::tree::TerminalNode *> COMMA();
    antlr4::tree::TerminalNode* COMMA(size_t i);

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnTypeExprSimpleContext : public ColumnTypeExprContext {
  public:
    ColumnTypeExprSimpleContext(ColumnTypeExprContext *ctx);

    IdentifierContext *identifier();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnTypeExprEnumContext : public ColumnTypeExprContext {
  public:
    ColumnTypeExprEnumContext(ColumnTypeExprContext *ctx);

    IdentifierContext *identifier();
    antlr4::tree::TerminalNode *LPAREN();
    std::vector<EnumValueContext *> enumValue();
    EnumValueContext* enumValue(size_t i);
    antlr4::tree::TerminalNode *RPAREN();
    std::vector<antlr4::tree::TerminalNode *> COMMA();
    antlr4::tree::TerminalNode* COMMA(size_t i);

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnTypeExprCompoundContext : public ColumnTypeExprContext {
  public:
    ColumnTypeExprCompoundContext(ColumnTypeExprContext *ctx);

    std::vector<IdentifierContext *> identifier();
    IdentifierContext* identifier(size_t i);

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  ColumnTypeExprContext* columnTypeExpr();
  ColumnTypeExprContext* columnTypeExpr(int precedence);
  class  ColumnTypeCastExprContext : public antlr4::ParserRuleContext {
  public:
    ColumnTypeCastExprContext(antlr4::ParserRuleContext *parent, size_t invokingState);
   
    ColumnTypeCastExprContext() = default;
    void copyFrom(ColumnTypeCastExprContext *context);
    using antlr4::ParserRuleContext::copyFrom;

    virtual size_t getRuleIndex() const override;

   
  };

  class  ColumnTypeCastExprCompoundContext : public ColumnTypeCastExprContext {
  public:
    ColumnTypeCastExprCompoundContext(ColumnTypeCastExprContext *ctx);

    std::vector<IdentifierContext *> identifier();
    IdentifierContext* identifier(size_t i);

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnTypeCastExprSimpleContext : public ColumnTypeCastExprContext {
  public:
    ColumnTypeCastExprSimpleContext(ColumnTypeCastExprContext *ctx);

    IdentifierContext *identifier();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  ColumnTypeCastExprContext* columnTypeCastExpr();

  class  ColumnExprListContext : public antlr4::ParserRuleContext {
  public:
    ColumnExprListContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    std::vector<ColumnExprContext *> columnExpr();
    ColumnExprContext* columnExpr(size_t i);
    std::vector<antlr4::tree::TerminalNode *> COMMA();
    antlr4::tree::TerminalNode* COMMA(size_t i);


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  ColumnExprListContext* columnExprList();

  class  SelectColumnExprListContext : public antlr4::ParserRuleContext {
  public:
    SelectColumnExprListContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    std::vector<SelectColumnExprContext *> selectColumnExpr();
    SelectColumnExprContext* selectColumnExpr(size_t i);
    std::vector<antlr4::tree::TerminalNode *> COMMA();
    antlr4::tree::TerminalNode* COMMA(size_t i);


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  SelectColumnExprListContext* selectColumnExprList();

  class  SelectColumnExprContext : public antlr4::ParserRuleContext {
  public:
    SelectColumnExprContext(antlr4::ParserRuleContext *parent, size_t invokingState);
   
    SelectColumnExprContext() = default;
    void copyFrom(SelectColumnExprContext *context);
    using antlr4::ParserRuleContext::copyFrom;

    virtual size_t getRuleIndex() const override;

   
  };

  class  ColumnExprAliasBeforeContext : public SelectColumnExprContext {
  public:
    ColumnExprAliasBeforeContext(SelectColumnExprContext *ctx);

    IdentifierContext *identifier();
    antlr4::tree::TerminalNode *COLON();
    ColumnExprContext *columnExpr();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprSelectValueContext : public SelectColumnExprContext {
  public:
    ColumnExprSelectValueContext(SelectColumnExprContext *ctx);

    ColumnExprContext *columnExpr();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  SelectColumnExprContext* selectColumnExpr();

  class  ColumnExprContext : public antlr4::ParserRuleContext {
  public:
    ColumnExprContext(antlr4::ParserRuleContext *parent, size_t invokingState);
   
    ColumnExprContext() = default;
    void copyFrom(ColumnExprContext *context);
    using antlr4::ParserRuleContext::copyFrom;

    virtual size_t getRuleIndex() const override;

   
  };

  class  ColumnExprColumnsAllContext : public ColumnExprContext {
  public:
    ColumnExprColumnsAllContext(ColumnExprContext *ctx);

    antlr4::tree::TerminalNode *COLUMNS();
    antlr4::tree::TerminalNode *LPAREN();
    antlr4::tree::TerminalNode *ASTERISK();
    antlr4::tree::TerminalNode *RPAREN();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprTernaryOpContext : public ColumnExprContext {
  public:
    ColumnExprTernaryOpContext(ColumnExprContext *ctx);

    std::vector<ColumnExprContext *> columnExpr();
    ColumnExprContext* columnExpr(size_t i);
    antlr4::tree::TerminalNode *QUERY();
    antlr4::tree::TerminalNode *COLON();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprAliasContext : public ColumnExprContext {
  public:
    ColumnExprAliasContext(ColumnExprContext *ctx);

    ColumnExprContext *columnExpr();
    antlr4::tree::TerminalNode *AS();
    IdentifierContext *identifier();
    antlr4::tree::TerminalNode *STRING_LITERAL();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprNegateContext : public ColumnExprContext {
  public:
    ColumnExprNegateContext(ColumnExprContext *ctx);

    antlr4::tree::TerminalNode *DASH();
    ColumnExprContext *columnExpr();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprLiteralContext : public ColumnExprContext {
  public:
    ColumnExprLiteralContext(ColumnExprContext *ctx);

    LiteralContext *literal();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprArrayContext : public ColumnExprContext {
  public:
    ColumnExprArrayContext(ColumnExprContext *ctx);

    antlr4::tree::TerminalNode *LBRACKET();
    antlr4::tree::TerminalNode *RBRACKET();
    antlr4::tree::TerminalNode *ARRAY();
    ColumnExprListContext *columnExprList();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprOrContext : public ColumnExprContext {
  public:
    ColumnExprOrContext(ColumnExprContext *ctx);

    std::vector<ColumnExprContext *> columnExpr();
    ColumnExprContext* columnExpr(size_t i);
    antlr4::tree::TerminalNode *OR();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprPrecedence1Context : public ColumnExprContext {
  public:
    ColumnExprPrecedence1Context(ColumnExprContext *ctx);

    HogQLParser::ColumnExprContext *left = nullptr;
    antlr4::Token *operator_ = nullptr;
    HogQLParser::ColumnExprContext *right = nullptr;
    std::vector<ColumnExprContext *> columnExpr();
    ColumnExprContext* columnExpr(size_t i);
    antlr4::tree::TerminalNode *ASTERISK();
    antlr4::tree::TerminalNode *SLASH();
    antlr4::tree::TerminalNode *PERCENT();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprPrecedence2Context : public ColumnExprContext {
  public:
    ColumnExprPrecedence2Context(ColumnExprContext *ctx);

    HogQLParser::ColumnExprContext *left = nullptr;
    antlr4::Token *operator_ = nullptr;
    HogQLParser::ColumnExprContext *right = nullptr;
    std::vector<ColumnExprContext *> columnExpr();
    ColumnExprContext* columnExpr(size_t i);
    antlr4::tree::TerminalNode *PLUS();
    antlr4::tree::TerminalNode *DASH();
    antlr4::tree::TerminalNode *CONCAT();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprPrecedence3Context : public ColumnExprContext {
  public:
    ColumnExprPrecedence3Context(ColumnExprContext *ctx);

    HogQLParser::ColumnExprContext *left = nullptr;
    antlr4::Token *operator_ = nullptr;
    HogQLParser::ColumnExprContext *right = nullptr;
    std::vector<ColumnExprContext *> columnExpr();
    ColumnExprContext* columnExpr(size_t i);
    antlr4::tree::TerminalNode *IN();
    antlr4::tree::TerminalNode *EQ_DOUBLE();
    antlr4::tree::TerminalNode *EQ_SINGLE();
    antlr4::tree::TerminalNode *NOT_EQ();
    antlr4::tree::TerminalNode *LT_EQ();
    antlr4::tree::TerminalNode *LT();
    antlr4::tree::TerminalNode *GT_EQ();
    antlr4::tree::TerminalNode *GT();
    antlr4::tree::TerminalNode *LIKE();
    antlr4::tree::TerminalNode *ILIKE();
    antlr4::tree::TerminalNode *REGEX_SINGLE();
    antlr4::tree::TerminalNode *REGEX_DOUBLE();
    antlr4::tree::TerminalNode *NOT_REGEX();
    antlr4::tree::TerminalNode *IREGEX_SINGLE();
    antlr4::tree::TerminalNode *IREGEX_DOUBLE();
    antlr4::tree::TerminalNode *NOT_IREGEX();
    antlr4::tree::TerminalNode *COHORT();
    antlr4::tree::TerminalNode *NOT();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprIntervalContext : public ColumnExprContext {
  public:
    ColumnExprIntervalContext(ColumnExprContext *ctx);

    antlr4::tree::TerminalNode *INTERVAL();
    ColumnExprContext *columnExpr();
    IntervalContext *interval();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprIsNullContext : public ColumnExprContext {
  public:
    ColumnExprIsNullContext(ColumnExprContext *ctx);

    ColumnExprContext *columnExpr();
    antlr4::tree::TerminalNode *IS();
    antlr4::tree::TerminalNode *NULL_SQL();
    antlr4::tree::TerminalNode *NOT();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprWinFunctionTargetContext : public ColumnExprContext {
  public:
    ColumnExprWinFunctionTargetContext(ColumnExprContext *ctx);

    HogQLParser::ColumnExprListContext *columnExprs = nullptr;
    HogQLParser::ColumnExprListContext *columnArgList = nullptr;
    HogQLParser::ColumnExprContext *filterExpr = nullptr;
    std::vector<IdentifierContext *> identifier();
    IdentifierContext* identifier(size_t i);
    antlr4::tree::TerminalNode *OVER();
    std::vector<antlr4::tree::TerminalNode *> LPAREN();
    antlr4::tree::TerminalNode* LPAREN(size_t i);
    std::vector<antlr4::tree::TerminalNode *> RPAREN();
    antlr4::tree::TerminalNode* RPAREN(size_t i);
    antlr4::tree::TerminalNode *FILTER();
    antlr4::tree::TerminalNode *WHERE();
    ColumnExprContext *columnExpr();
    std::vector<ColumnExprListContext *> columnExprList();
    ColumnExprListContext* columnExprList(size_t i);
    antlr4::tree::TerminalNode *DISTINCT();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprNamedArgContext : public ColumnExprContext {
  public:
    ColumnExprNamedArgContext(ColumnExprContext *ctx);

    IdentifierContext *identifier();
    antlr4::tree::TerminalNode *COLONEQUALS();
    ColumnExprContext *columnExpr();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprNullPropertyAccessContext : public ColumnExprContext {
  public:
    ColumnExprNullPropertyAccessContext(ColumnExprContext *ctx);

    ColumnExprContext *columnExpr();
    antlr4::tree::TerminalNode *NULL_PROPERTY();
    IdentifierContext *identifier();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprIntervalStringContext : public ColumnExprContext {
  public:
    ColumnExprIntervalStringContext(ColumnExprContext *ctx);

    antlr4::tree::TerminalNode *INTERVAL();
    antlr4::tree::TerminalNode *STRING_LITERAL();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprTagElementContext : public ColumnExprContext {
  public:
    ColumnExprTagElementContext(ColumnExprContext *ctx);

    HogqlxTagElementContext *hogqlxTagElement();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprCallContext : public ColumnExprContext {
  public:
    ColumnExprCallContext(ColumnExprContext *ctx);

    ColumnExprContext *columnExpr();
    antlr4::tree::TerminalNode *LPAREN();
    antlr4::tree::TerminalNode *RPAREN();
    ColumnExprListContext *columnExprList();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprArrayAccessContext : public ColumnExprContext {
  public:
    ColumnExprArrayAccessContext(ColumnExprContext *ctx);

    std::vector<ColumnExprContext *> columnExpr();
    ColumnExprContext* columnExpr(size_t i);
    antlr4::tree::TerminalNode *LBRACKET();
    antlr4::tree::TerminalNode *RBRACKET();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprBetweenContext : public ColumnExprContext {
  public:
    ColumnExprBetweenContext(ColumnExprContext *ctx);

    std::vector<ColumnExprContext *> columnExpr();
    ColumnExprContext* columnExpr(size_t i);
    antlr4::tree::TerminalNode *BETWEEN();
    antlr4::tree::TerminalNode *AND();
    antlr4::tree::TerminalNode *NOT();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprParensContext : public ColumnExprContext {
  public:
    ColumnExprParensContext(ColumnExprContext *ctx);

    antlr4::tree::TerminalNode *LPAREN();
    ColumnExprContext *columnExpr();
    antlr4::tree::TerminalNode *RPAREN();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprTimestampContext : public ColumnExprContext {
  public:
    ColumnExprTimestampContext(ColumnExprContext *ctx);

    antlr4::tree::TerminalNode *TIMESTAMP();
    antlr4::tree::TerminalNode *STRING_LITERAL();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprAndContext : public ColumnExprContext {
  public:
    ColumnExprAndContext(ColumnExprContext *ctx);

    std::vector<ColumnExprContext *> columnExpr();
    ColumnExprContext* columnExpr(size_t i);
    antlr4::tree::TerminalNode *AND();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprColumnsQualifiedExcludeContext : public ColumnExprContext {
  public:
    ColumnExprColumnsQualifiedExcludeContext(ColumnExprContext *ctx);

    antlr4::tree::TerminalNode *COLUMNS();
    std::vector<antlr4::tree::TerminalNode *> LPAREN();
    antlr4::tree::TerminalNode* LPAREN(size_t i);
    IdentifierContext *identifier();
    antlr4::tree::TerminalNode *DOT();
    antlr4::tree::TerminalNode *ASTERISK();
    antlr4::tree::TerminalNode *EXCLUDE();
    IdentifierListContext *identifierList();
    std::vector<antlr4::tree::TerminalNode *> RPAREN();
    antlr4::tree::TerminalNode* RPAREN(size_t i);

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprNotContext : public ColumnExprContext {
  public:
    ColumnExprNotContext(ColumnExprContext *ctx);

    antlr4::tree::TerminalNode *NOT();
    ColumnExprContext *columnExpr();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprFunctionContext : public ColumnExprContext {
  public:
    ColumnExprFunctionContext(ColumnExprContext *ctx);

    HogQLParser::ColumnExprListContext *columnExprs = nullptr;
    HogQLParser::ColumnExprListContext *columnArgList = nullptr;
    HogQLParser::ColumnExprContext *filterExpr = nullptr;
    IdentifierContext *identifier();
    std::vector<antlr4::tree::TerminalNode *> LPAREN();
    antlr4::tree::TerminalNode* LPAREN(size_t i);
    std::vector<antlr4::tree::TerminalNode *> RPAREN();
    antlr4::tree::TerminalNode* RPAREN(size_t i);
    antlr4::tree::TerminalNode *DISTINCT();
    antlr4::tree::TerminalNode *ORDER();
    antlr4::tree::TerminalNode *BY();
    OrderExprListContext *orderExprList();
    antlr4::tree::TerminalNode *FILTER();
    antlr4::tree::TerminalNode *WHERE();
    std::vector<ColumnExprListContext *> columnExprList();
    ColumnExprListContext* columnExprList(size_t i);
    ColumnExprContext *columnExpr();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprDictContext : public ColumnExprContext {
  public:
    ColumnExprDictContext(ColumnExprContext *ctx);

    antlr4::tree::TerminalNode *LBRACE();
    antlr4::tree::TerminalNode *RBRACE();
    KvPairListContext *kvPairList();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprSubqueryContext : public ColumnExprContext {
  public:
    ColumnExprSubqueryContext(ColumnExprContext *ctx);

    antlr4::tree::TerminalNode *LPAREN();
    SelectSetStmtContext *selectSetStmt();
    antlr4::tree::TerminalNode *RPAREN();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprSubstringContext : public ColumnExprContext {
  public:
    ColumnExprSubstringContext(ColumnExprContext *ctx);

    antlr4::tree::TerminalNode *SUBSTRING();
    antlr4::tree::TerminalNode *LPAREN();
    std::vector<ColumnExprContext *> columnExpr();
    ColumnExprContext* columnExpr(size_t i);
    antlr4::tree::TerminalNode *FROM();
    antlr4::tree::TerminalNode *RPAREN();
    antlr4::tree::TerminalNode *FOR();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprCastContext : public ColumnExprContext {
  public:
    ColumnExprCastContext(ColumnExprContext *ctx);

    antlr4::tree::TerminalNode *CAST();
    antlr4::tree::TerminalNode *LPAREN();
    ColumnExprContext *columnExpr();
    antlr4::tree::TerminalNode *AS();
    ColumnTypeExprContext *columnTypeExpr();
    antlr4::tree::TerminalNode *RPAREN();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprArraySliceContext : public ColumnExprContext {
  public:
    ColumnExprArraySliceContext(ColumnExprContext *ctx);

    std::vector<ColumnExprContext *> columnExpr();
    ColumnExprContext* columnExpr(size_t i);
    antlr4::tree::TerminalNode *LBRACKET();
    antlr4::tree::TerminalNode *COLON();
    antlr4::tree::TerminalNode *RBRACKET();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprColumnsQualifiedReplaceContext : public ColumnExprContext {
  public:
    ColumnExprColumnsQualifiedReplaceContext(ColumnExprContext *ctx);

    antlr4::tree::TerminalNode *COLUMNS();
    std::vector<antlr4::tree::TerminalNode *> LPAREN();
    antlr4::tree::TerminalNode* LPAREN(size_t i);
    IdentifierContext *identifier();
    antlr4::tree::TerminalNode *DOT();
    antlr4::tree::TerminalNode *ASTERISK();
    antlr4::tree::TerminalNode *REPLACE();
    ColumnsReplaceListContext *columnsReplaceList();
    std::vector<antlr4::tree::TerminalNode *> RPAREN();
    antlr4::tree::TerminalNode* RPAREN(size_t i);

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprNullTupleAccessContext : public ColumnExprContext {
  public:
    ColumnExprNullTupleAccessContext(ColumnExprContext *ctx);

    ColumnExprContext *columnExpr();
    antlr4::tree::TerminalNode *NULL_PROPERTY();
    antlr4::tree::TerminalNode *DECIMAL_LITERAL();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprFunctionWithinGroupContext : public ColumnExprContext {
  public:
    ColumnExprFunctionWithinGroupContext(ColumnExprContext *ctx);

    HogQLParser::ColumnExprListContext *columnExprs = nullptr;
    IdentifierContext *identifier();
    antlr4::tree::TerminalNode *LPAREN();
    antlr4::tree::TerminalNode *RPAREN();
    WithinGroupClauseContext *withinGroupClause();
    ColumnExprListContext *columnExprList();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprPositionalContext : public ColumnExprContext {
  public:
    ColumnExprPositionalContext(ColumnExprContext *ctx);

    antlr4::tree::TerminalNode *HASH();
    antlr4::tree::TerminalNode *DECIMAL_LITERAL();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprColumnsRegexContext : public ColumnExprContext {
  public:
    ColumnExprColumnsRegexContext(ColumnExprContext *ctx);

    antlr4::tree::TerminalNode *COLUMNS();
    antlr4::tree::TerminalNode *LPAREN();
    antlr4::tree::TerminalNode *STRING_LITERAL();
    antlr4::tree::TerminalNode *RPAREN();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprTypeCastContext : public ColumnExprContext {
  public:
    ColumnExprTypeCastContext(ColumnExprContext *ctx);

    ColumnExprContext *columnExpr();
    antlr4::tree::TerminalNode *DOUBLECOLON();
    ColumnTypeCastExprContext *columnTypeCastExpr();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprIsDistinctFromContext : public ColumnExprContext {
  public:
    ColumnExprIsDistinctFromContext(ColumnExprContext *ctx);

    std::vector<ColumnExprContext *> columnExpr();
    ColumnExprContext* columnExpr(size_t i);
    antlr4::tree::TerminalNode *IS();
    antlr4::tree::TerminalNode *DISTINCT();
    antlr4::tree::TerminalNode *FROM();
    antlr4::tree::TerminalNode *NOT();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprSpreadColumnsListContext : public ColumnExprContext {
  public:
    ColumnExprSpreadColumnsListContext(ColumnExprContext *ctx);

    antlr4::tree::TerminalNode *ASTERISK();
    antlr4::tree::TerminalNode *COLUMNS();
    antlr4::tree::TerminalNode *LPAREN();
    ColumnExprListContext *columnExprList();
    antlr4::tree::TerminalNode *RPAREN();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprColumnsExcludeReplaceContext : public ColumnExprContext {
  public:
    ColumnExprColumnsExcludeReplaceContext(ColumnExprContext *ctx);

    antlr4::tree::TerminalNode *COLUMNS();
    std::vector<antlr4::tree::TerminalNode *> LPAREN();
    antlr4::tree::TerminalNode* LPAREN(size_t i);
    antlr4::tree::TerminalNode *ASTERISK();
    antlr4::tree::TerminalNode *EXCLUDE();
    IdentifierListContext *identifierList();
    std::vector<antlr4::tree::TerminalNode *> RPAREN();
    antlr4::tree::TerminalNode* RPAREN(size_t i);
    antlr4::tree::TerminalNode *REPLACE();
    ColumnsReplaceListContext *columnsReplaceList();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprColumnsQualifiedExcludeReplaceContext : public ColumnExprContext {
  public:
    ColumnExprColumnsQualifiedExcludeReplaceContext(ColumnExprContext *ctx);

    antlr4::tree::TerminalNode *COLUMNS();
    std::vector<antlr4::tree::TerminalNode *> LPAREN();
    antlr4::tree::TerminalNode* LPAREN(size_t i);
    IdentifierContext *identifier();
    antlr4::tree::TerminalNode *DOT();
    antlr4::tree::TerminalNode *ASTERISK();
    antlr4::tree::TerminalNode *EXCLUDE();
    IdentifierListContext *identifierList();
    std::vector<antlr4::tree::TerminalNode *> RPAREN();
    antlr4::tree::TerminalNode* RPAREN(size_t i);
    antlr4::tree::TerminalNode *REPLACE();
    ColumnsReplaceListContext *columnsReplaceList();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprColumnsExcludeContext : public ColumnExprContext {
  public:
    ColumnExprColumnsExcludeContext(ColumnExprContext *ctx);

    antlr4::tree::TerminalNode *COLUMNS();
    std::vector<antlr4::tree::TerminalNode *> LPAREN();
    antlr4::tree::TerminalNode* LPAREN(size_t i);
    antlr4::tree::TerminalNode *ASTERISK();
    antlr4::tree::TerminalNode *EXCLUDE();
    IdentifierListContext *identifierList();
    std::vector<antlr4::tree::TerminalNode *> RPAREN();
    antlr4::tree::TerminalNode* RPAREN(size_t i);

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprColonLambdaContext : public ColumnExprContext {
  public:
    ColumnExprColonLambdaContext(ColumnExprContext *ctx);

    antlr4::tree::TerminalNode *LAMBDA();
    std::vector<IdentifierContext *> identifier();
    IdentifierContext* identifier(size_t i);
    antlr4::tree::TerminalNode *COLON();
    ColumnExprContext *columnExpr();
    std::vector<antlr4::tree::TerminalNode *> COMMA();
    antlr4::tree::TerminalNode* COMMA(size_t i);

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprCallSelectContext : public ColumnExprContext {
  public:
    ColumnExprCallSelectContext(ColumnExprContext *ctx);

    ColumnExprContext *columnExpr();
    antlr4::tree::TerminalNode *LPAREN();
    SelectSetStmtContext *selectSetStmt();
    antlr4::tree::TerminalNode *RPAREN();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprColumnsQualifiedAllContext : public ColumnExprContext {
  public:
    ColumnExprColumnsQualifiedAllContext(ColumnExprContext *ctx);

    antlr4::tree::TerminalNode *COLUMNS();
    antlr4::tree::TerminalNode *LPAREN();
    IdentifierContext *identifier();
    antlr4::tree::TerminalNode *DOT();
    antlr4::tree::TerminalNode *ASTERISK();
    antlr4::tree::TerminalNode *RPAREN();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprTrimContext : public ColumnExprContext {
  public:
    ColumnExprTrimContext(ColumnExprContext *ctx);

    antlr4::tree::TerminalNode *TRIM();
    antlr4::tree::TerminalNode *LPAREN();
    StringContext *string();
    antlr4::tree::TerminalNode *FROM();
    ColumnExprContext *columnExpr();
    antlr4::tree::TerminalNode *RPAREN();
    antlr4::tree::TerminalNode *BOTH();
    antlr4::tree::TerminalNode *LEADING();
    antlr4::tree::TerminalNode *TRAILING();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprTemplateStringContext : public ColumnExprContext {
  public:
    ColumnExprTemplateStringContext(ColumnExprContext *ctx);

    TemplateStringContext *templateString();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprTupleContext : public ColumnExprContext {
  public:
    ColumnExprTupleContext(ColumnExprContext *ctx);

    antlr4::tree::TerminalNode *LPAREN();
    ColumnExprListContext *columnExprList();
    antlr4::tree::TerminalNode *RPAREN();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprTryCastContext : public ColumnExprContext {
  public:
    ColumnExprTryCastContext(ColumnExprContext *ctx);

    antlr4::tree::TerminalNode *TRY_CAST();
    antlr4::tree::TerminalNode *LPAREN();
    ColumnExprContext *columnExpr();
    antlr4::tree::TerminalNode *AS();
    ColumnTypeExprContext *columnTypeExpr();
    antlr4::tree::TerminalNode *RPAREN();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprColumnsListContext : public ColumnExprContext {
  public:
    ColumnExprColumnsListContext(ColumnExprContext *ctx);

    antlr4::tree::TerminalNode *COLUMNS();
    antlr4::tree::TerminalNode *LPAREN();
    ColumnExprListContext *columnExprList();
    antlr4::tree::TerminalNode *RPAREN();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprColumnsReplaceContext : public ColumnExprContext {
  public:
    ColumnExprColumnsReplaceContext(ColumnExprContext *ctx);

    antlr4::tree::TerminalNode *COLUMNS();
    std::vector<antlr4::tree::TerminalNode *> LPAREN();
    antlr4::tree::TerminalNode* LPAREN(size_t i);
    antlr4::tree::TerminalNode *ASTERISK();
    antlr4::tree::TerminalNode *REPLACE();
    ColumnsReplaceListContext *columnsReplaceList();
    std::vector<antlr4::tree::TerminalNode *> RPAREN();
    antlr4::tree::TerminalNode* RPAREN(size_t i);

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprSpreadColumnsRegexContext : public ColumnExprContext {
  public:
    ColumnExprSpreadColumnsRegexContext(ColumnExprContext *ctx);

    antlr4::tree::TerminalNode *ASTERISK();
    antlr4::tree::TerminalNode *COLUMNS();
    antlr4::tree::TerminalNode *LPAREN();
    antlr4::tree::TerminalNode *STRING_LITERAL();
    antlr4::tree::TerminalNode *RPAREN();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprPropertyAccessContext : public ColumnExprContext {
  public:
    ColumnExprPropertyAccessContext(ColumnExprContext *ctx);

    ColumnExprContext *columnExpr();
    antlr4::tree::TerminalNode *DOT();
    IdentifierContext *identifier();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprNullArrayAccessContext : public ColumnExprContext {
  public:
    ColumnExprNullArrayAccessContext(ColumnExprContext *ctx);

    std::vector<ColumnExprContext *> columnExpr();
    ColumnExprContext* columnExpr(size_t i);
    antlr4::tree::TerminalNode *NULL_PROPERTY();
    antlr4::tree::TerminalNode *LBRACKET();
    antlr4::tree::TerminalNode *RBRACKET();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprIgnoreNullsContext : public ColumnExprContext {
  public:
    ColumnExprIgnoreNullsContext(ColumnExprContext *ctx);

    ColumnExprContext *columnExpr();
    antlr4::tree::TerminalNode *IGNORE();
    antlr4::tree::TerminalNode *NULLS();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprNullishContext : public ColumnExprContext {
  public:
    ColumnExprNullishContext(ColumnExprContext *ctx);

    std::vector<ColumnExprContext *> columnExpr();
    ColumnExprContext* columnExpr(size_t i);
    antlr4::tree::TerminalNode *NULLISH();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprTupleAccessContext : public ColumnExprContext {
  public:
    ColumnExprTupleAccessContext(ColumnExprContext *ctx);

    ColumnExprContext *columnExpr();
    antlr4::tree::TerminalNode *DOT();
    antlr4::tree::TerminalNode *DECIMAL_LITERAL();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprCaseContext : public ColumnExprContext {
  public:
    ColumnExprCaseContext(ColumnExprContext *ctx);

    HogQLParser::ColumnExprContext *caseExpr = nullptr;
    HogQLParser::ColumnExprContext *whenExpr = nullptr;
    HogQLParser::ColumnExprContext *thenExpr = nullptr;
    HogQLParser::ColumnExprContext *elseExpr = nullptr;
    antlr4::tree::TerminalNode *CASE();
    antlr4::tree::TerminalNode *END();
    std::vector<antlr4::tree::TerminalNode *> WHEN();
    antlr4::tree::TerminalNode* WHEN(size_t i);
    std::vector<antlr4::tree::TerminalNode *> THEN();
    antlr4::tree::TerminalNode* THEN(size_t i);
    antlr4::tree::TerminalNode *ELSE();
    std::vector<ColumnExprContext *> columnExpr();
    ColumnExprContext* columnExpr(size_t i);

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprDateContext : public ColumnExprContext {
  public:
    ColumnExprDateContext(ColumnExprContext *ctx);

    antlr4::tree::TerminalNode *DATE();
    antlr4::tree::TerminalNode *STRING_LITERAL();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprWinFunctionContext : public ColumnExprContext {
  public:
    ColumnExprWinFunctionContext(ColumnExprContext *ctx);

    HogQLParser::ColumnExprListContext *columnExprs = nullptr;
    HogQLParser::ColumnExprListContext *columnArgList = nullptr;
    HogQLParser::ColumnExprContext *filterExpr = nullptr;
    IdentifierContext *identifier();
    antlr4::tree::TerminalNode *OVER();
    std::vector<antlr4::tree::TerminalNode *> LPAREN();
    antlr4::tree::TerminalNode* LPAREN(size_t i);
    WindowExprContext *windowExpr();
    std::vector<antlr4::tree::TerminalNode *> RPAREN();
    antlr4::tree::TerminalNode* RPAREN(size_t i);
    antlr4::tree::TerminalNode *FILTER();
    antlr4::tree::TerminalNode *WHERE();
    ColumnExprContext *columnExpr();
    std::vector<ColumnExprListContext *> columnExprList();
    ColumnExprListContext* columnExprList(size_t i);
    antlr4::tree::TerminalNode *DISTINCT();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprLambdaContext : public ColumnExprContext {
  public:
    ColumnExprLambdaContext(ColumnExprContext *ctx);

    ColumnLambdaExprContext *columnLambdaExpr();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprIdentifierContext : public ColumnExprContext {
  public:
    ColumnExprIdentifierContext(ColumnExprContext *ctx);

    ColumnIdentifierContext *columnIdentifier();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprAsteriskContext : public ColumnExprContext {
  public:
    ColumnExprAsteriskContext(ColumnExprContext *ctx);

    antlr4::tree::TerminalNode *ASTERISK();
    TableIdentifierContext *tableIdentifier();
    antlr4::tree::TerminalNode *DOT();
    antlr4::tree::TerminalNode *EXCLUDE();
    antlr4::tree::TerminalNode *LPAREN();
    IdentifierListContext *identifierList();
    antlr4::tree::TerminalNode *RPAREN();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  ColumnExprContext* columnExpr();
  ColumnExprContext* columnExpr(int precedence);
  class  ColumnLambdaExprContext : public antlr4::ParserRuleContext {
  public:
    ColumnLambdaExprContext(antlr4::ParserRuleContext *parent, size_t invokingState);
   
    ColumnLambdaExprContext() = default;
    void copyFrom(ColumnLambdaExprContext *context);
    using antlr4::ParserRuleContext::copyFrom;

    virtual size_t getRuleIndex() const override;

   
  };

  class  ArrowLambdaContext : public ColumnLambdaExprContext {
  public:
    ArrowLambdaContext(ColumnLambdaExprContext *ctx);

    antlr4::tree::TerminalNode *ARROW();
    antlr4::tree::TerminalNode *LPAREN();
    std::vector<IdentifierContext *> identifier();
    IdentifierContext* identifier(size_t i);
    antlr4::tree::TerminalNode *RPAREN();
    ColumnExprContext *columnExpr();
    BlockContext *block();
    std::vector<antlr4::tree::TerminalNode *> COMMA();
    antlr4::tree::TerminalNode* COMMA(size_t i);

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColonLambdaContext : public ColumnLambdaExprContext {
  public:
    ColonLambdaContext(ColumnLambdaExprContext *ctx);

    antlr4::tree::TerminalNode *LAMBDA();
    std::vector<IdentifierContext *> identifier();
    IdentifierContext* identifier(size_t i);
    antlr4::tree::TerminalNode *COLON();
    ColumnExprContext *columnExpr();
    std::vector<antlr4::tree::TerminalNode *> COMMA();
    antlr4::tree::TerminalNode* COMMA(size_t i);

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  ColumnLambdaExprContext* columnLambdaExpr();

  class  ColumnsReplaceListContext : public antlr4::ParserRuleContext {
  public:
    ColumnsReplaceListContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    std::vector<ColumnsReplaceItemContext *> columnsReplaceItem();
    ColumnsReplaceItemContext* columnsReplaceItem(size_t i);
    std::vector<antlr4::tree::TerminalNode *> COMMA();
    antlr4::tree::TerminalNode* COMMA(size_t i);


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  ColumnsReplaceListContext* columnsReplaceList();

  class  ColumnsReplaceItemContext : public antlr4::ParserRuleContext {
  public:
    ColumnsReplaceItemContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    ColumnExprContext *columnExpr();
    antlr4::tree::TerminalNode *AS();
    IdentifierContext *identifier();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  ColumnsReplaceItemContext* columnsReplaceItem();

  class  HogqlxChildElementContext : public antlr4::ParserRuleContext {
  public:
    HogqlxChildElementContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    HogqlxTagElementContext *hogqlxTagElement();
    HogqlxTextContext *hogqlxText();
    antlr4::tree::TerminalNode *LBRACE();
    ColumnExprContext *columnExpr();
    antlr4::tree::TerminalNode *RBRACE();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  HogqlxChildElementContext* hogqlxChildElement();

  class  HogqlxTextContext : public antlr4::ParserRuleContext {
  public:
    HogqlxTextContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *HOGQLX_TEXT_TEXT();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  HogqlxTextContext* hogqlxText();

  class  HogqlxTagElementContext : public antlr4::ParserRuleContext {
  public:
    HogqlxTagElementContext(antlr4::ParserRuleContext *parent, size_t invokingState);
   
    HogqlxTagElementContext() = default;
    void copyFrom(HogqlxTagElementContext *context);
    using antlr4::ParserRuleContext::copyFrom;

    virtual size_t getRuleIndex() const override;

   
  };

  class  HogqlxTagElementClosedContext : public HogqlxTagElementContext {
  public:
    HogqlxTagElementClosedContext(HogqlxTagElementContext *ctx);

    antlr4::tree::TerminalNode *LT();
    IdentifierContext *identifier();
    antlr4::tree::TerminalNode *SLASH_GT();
    std::vector<HogqlxTagAttributeContext *> hogqlxTagAttribute();
    HogqlxTagAttributeContext* hogqlxTagAttribute(size_t i);

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  HogqlxTagElementNestedContext : public HogqlxTagElementContext {
  public:
    HogqlxTagElementNestedContext(HogqlxTagElementContext *ctx);

    antlr4::tree::TerminalNode *LT();
    std::vector<IdentifierContext *> identifier();
    IdentifierContext* identifier(size_t i);
    std::vector<antlr4::tree::TerminalNode *> GT();
    antlr4::tree::TerminalNode* GT(size_t i);
    antlr4::tree::TerminalNode *LT_SLASH();
    std::vector<HogqlxTagAttributeContext *> hogqlxTagAttribute();
    HogqlxTagAttributeContext* hogqlxTagAttribute(size_t i);
    std::vector<HogqlxChildElementContext *> hogqlxChildElement();
    HogqlxChildElementContext* hogqlxChildElement(size_t i);

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  HogqlxTagElementContext* hogqlxTagElement();

  class  HogqlxTagAttributeContext : public antlr4::ParserRuleContext {
  public:
    HogqlxTagAttributeContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    IdentifierContext *identifier();
    antlr4::tree::TerminalNode *EQ_SINGLE();
    StringContext *string();
    antlr4::tree::TerminalNode *LBRACE();
    ColumnExprContext *columnExpr();
    antlr4::tree::TerminalNode *RBRACE();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  HogqlxTagAttributeContext* hogqlxTagAttribute();

  class  WithExprListContext : public antlr4::ParserRuleContext {
  public:
    WithExprListContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    std::vector<WithExprContext *> withExpr();
    WithExprContext* withExpr(size_t i);
    std::vector<antlr4::tree::TerminalNode *> COMMA();
    antlr4::tree::TerminalNode* COMMA(size_t i);


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  WithExprListContext* withExprList();

  class  WithExprContext : public antlr4::ParserRuleContext {
  public:
    WithExprContext(antlr4::ParserRuleContext *parent, size_t invokingState);
   
    WithExprContext() = default;
    void copyFrom(WithExprContext *context);
    using antlr4::ParserRuleContext::copyFrom;

    virtual size_t getRuleIndex() const override;

   
  };

  class  WithExprColumnContext : public WithExprContext {
  public:
    WithExprColumnContext(WithExprContext *ctx);

    ColumnExprContext *columnExpr();
    antlr4::tree::TerminalNode *AS();
    IdentifierContext *identifier();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  WithExprSubqueryContext : public WithExprContext {
  public:
    WithExprSubqueryContext(WithExprContext *ctx);

    IdentifierContext *identifier();
    antlr4::tree::TerminalNode *AS();
    antlr4::tree::TerminalNode *LPAREN();
    SelectSetStmtContext *selectSetStmt();
    antlr4::tree::TerminalNode *RPAREN();
    std::vector<WithExprColumnNameListContext *> withExprColumnNameList();
    WithExprColumnNameListContext* withExprColumnNameList(size_t i);
    antlr4::tree::TerminalNode *USING();
    antlr4::tree::TerminalNode *KEY();
    antlr4::tree::TerminalNode *MATERIALIZED();
    antlr4::tree::TerminalNode *NOT();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  WithExprContext* withExpr();

  class  WithExprColumnNameListContext : public antlr4::ParserRuleContext {
  public:
    WithExprColumnNameListContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *LPAREN();
    std::vector<IdentifierContext *> identifier();
    IdentifierContext* identifier(size_t i);
    antlr4::tree::TerminalNode *RPAREN();
    std::vector<antlr4::tree::TerminalNode *> COMMA();
    antlr4::tree::TerminalNode* COMMA(size_t i);


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  WithExprColumnNameListContext* withExprColumnNameList();

  class  ColumnIdentifierContext : public antlr4::ParserRuleContext {
  public:
    ColumnIdentifierContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    PlaceholderContext *placeholder();
    NestedIdentifierContext *nestedIdentifier();
    TableIdentifierContext *tableIdentifier();
    antlr4::tree::TerminalNode *DOT();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  ColumnIdentifierContext* columnIdentifier();

  class  NestedIdentifierContext : public antlr4::ParserRuleContext {
  public:
    NestedIdentifierContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    std::vector<IdentifierContext *> identifier();
    IdentifierContext* identifier(size_t i);
    std::vector<antlr4::tree::TerminalNode *> DOT();
    antlr4::tree::TerminalNode* DOT(size_t i);


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  NestedIdentifierContext* nestedIdentifier();

  class  TableExprContext : public antlr4::ParserRuleContext {
  public:
    TableExprContext(antlr4::ParserRuleContext *parent, size_t invokingState);
   
    TableExprContext() = default;
    void copyFrom(TableExprContext *context);
    using antlr4::ParserRuleContext::copyFrom;

    virtual size_t getRuleIndex() const override;

   
  };

  class  TableExprTagContext : public TableExprContext {
  public:
    TableExprTagContext(TableExprContext *ctx);

    HogqlxTagElementContext *hogqlxTagElement();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  TableExprIdentifierContext : public TableExprContext {
  public:
    TableExprIdentifierContext(TableExprContext *ctx);

    TableIdentifierContext *tableIdentifier();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  TableExprPlaceholderContext : public TableExprContext {
  public:
    TableExprPlaceholderContext(TableExprContext *ctx);

    PlaceholderContext *placeholder();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  TableExprSubqueryContext : public TableExprContext {
  public:
    TableExprSubqueryContext(TableExprContext *ctx);

    antlr4::tree::TerminalNode *LPAREN();
    SelectSetStmtContext *selectSetStmt();
    antlr4::tree::TerminalNode *RPAREN();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  TableExprPivotContext : public TableExprContext {
  public:
    TableExprPivotContext(TableExprContext *ctx);

    TableExprContext *tableExpr();
    antlr4::tree::TerminalNode *PIVOT();
    antlr4::tree::TerminalNode *LPAREN();
    std::vector<ColumnExprListContext *> columnExprList();
    ColumnExprListContext* columnExprList(size_t i);
    PivotColumnListContext *pivotColumnList();
    antlr4::tree::TerminalNode *RPAREN();
    antlr4::tree::TerminalNode *GROUP();
    antlr4::tree::TerminalNode *BY();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  TableExprValuesContext : public TableExprContext {
  public:
    TableExprValuesContext(TableExprContext *ctx);

    antlr4::tree::TerminalNode *LPAREN();
    ValuesClauseContext *valuesClause();
    antlr4::tree::TerminalNode *RPAREN();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  TableExprAliasContext : public TableExprContext {
  public:
    TableExprAliasContext(TableExprContext *ctx);

    TableExprContext *tableExpr();
    AliasContext *alias();
    antlr4::tree::TerminalNode *AS();
    IdentifierContext *identifier();
    ColumnAliasesContext *columnAliases();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  TableExprFunctionContext : public TableExprContext {
  public:
    TableExprFunctionContext(TableExprContext *ctx);

    TableFunctionExprContext *tableFunctionExpr();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  TableExprUnpivotContext : public TableExprContext {
  public:
    TableExprUnpivotContext(TableExprContext *ctx);

    TableExprContext *tableExpr();
    antlr4::tree::TerminalNode *UNPIVOT();
    antlr4::tree::TerminalNode *LPAREN();
    UnpivotColumnListContext *unpivotColumnList();
    antlr4::tree::TerminalNode *RPAREN();
    antlr4::tree::TerminalNode *INCLUDE();
    antlr4::tree::TerminalNode *NULLS();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  TableExprContext* tableExpr();
  TableExprContext* tableExpr(int precedence);
  class  PivotColumnListContext : public antlr4::ParserRuleContext {
  public:
    PivotColumnListContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *FOR();
    std::vector<PivotColumnContext *> pivotColumn();
    PivotColumnContext* pivotColumn(size_t i);


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  PivotColumnListContext* pivotColumnList();

  class  PivotColumnContext : public antlr4::ParserRuleContext {
  public:
    PivotColumnContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    ColumnExprTupleOrSingleContext *columnExprTupleOrSingle();
    antlr4::tree::TerminalNode *IN();
    antlr4::tree::TerminalNode *LPAREN();
    ColumnExprListContext *columnExprList();
    antlr4::tree::TerminalNode *RPAREN();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  PivotColumnContext* pivotColumn();

  class  UnpivotColumnListContext : public antlr4::ParserRuleContext {
  public:
    UnpivotColumnListContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    std::vector<UnpivotColumnContext *> unpivotColumn();
    UnpivotColumnContext* unpivotColumn(size_t i);
    std::vector<antlr4::tree::TerminalNode *> COMMA();
    antlr4::tree::TerminalNode* COMMA(size_t i);


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  UnpivotColumnListContext* unpivotColumnList();

  class  UnpivotColumnContext : public antlr4::ParserRuleContext {
  public:
    UnpivotColumnContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    std::vector<ColumnExprTupleOrSingleContext *> columnExprTupleOrSingle();
    ColumnExprTupleOrSingleContext* columnExprTupleOrSingle(size_t i);
    antlr4::tree::TerminalNode *FOR();
    std::vector<antlr4::tree::TerminalNode *> IN();
    antlr4::tree::TerminalNode* IN(size_t i);
    std::vector<antlr4::tree::TerminalNode *> LPAREN();
    antlr4::tree::TerminalNode* LPAREN(size_t i);
    std::vector<ColumnExprListContext *> columnExprList();
    ColumnExprListContext* columnExprList(size_t i);
    std::vector<antlr4::tree::TerminalNode *> RPAREN();
    antlr4::tree::TerminalNode* RPAREN(size_t i);


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  UnpivotColumnContext* unpivotColumn();

  class  ColumnExprTupleOrSingleContext : public antlr4::ParserRuleContext {
  public:
    ColumnExprTupleOrSingleContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *LPAREN();
    ColumnExprListContext *columnExprList();
    antlr4::tree::TerminalNode *RPAREN();
    ColumnExprContext *columnExpr();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  ColumnExprTupleOrSingleContext* columnExprTupleOrSingle();

  class  ColumnAliasesContext : public antlr4::ParserRuleContext {
  public:
    ColumnAliasesContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *LPAREN();
    std::vector<IdentifierContext *> identifier();
    IdentifierContext* identifier(size_t i);
    antlr4::tree::TerminalNode *RPAREN();
    std::vector<antlr4::tree::TerminalNode *> COMMA();
    antlr4::tree::TerminalNode* COMMA(size_t i);


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  ColumnAliasesContext* columnAliases();

  class  TableFunctionExprContext : public antlr4::ParserRuleContext {
  public:
    TableFunctionExprContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    IdentifierContext *identifier();
    antlr4::tree::TerminalNode *LPAREN();
    antlr4::tree::TerminalNode *RPAREN();
    TableArgListContext *tableArgList();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  TableFunctionExprContext* tableFunctionExpr();

  class  TableIdentifierContext : public antlr4::ParserRuleContext {
  public:
    TableIdentifierContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    NestedIdentifierContext *nestedIdentifier();
    DatabaseIdentifierContext *databaseIdentifier();
    antlr4::tree::TerminalNode *DOT();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  TableIdentifierContext* tableIdentifier();

  class  TableArgListContext : public antlr4::ParserRuleContext {
  public:
    TableArgListContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    std::vector<ColumnExprContext *> columnExpr();
    ColumnExprContext* columnExpr(size_t i);
    std::vector<antlr4::tree::TerminalNode *> COMMA();
    antlr4::tree::TerminalNode* COMMA(size_t i);


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  TableArgListContext* tableArgList();

  class  DatabaseIdentifierContext : public antlr4::ParserRuleContext {
  public:
    DatabaseIdentifierContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    IdentifierContext *identifier();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  DatabaseIdentifierContext* databaseIdentifier();

  class  FloatingLiteralContext : public antlr4::ParserRuleContext {
  public:
    FloatingLiteralContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *FLOATING_LITERAL();
    antlr4::tree::TerminalNode *DOT();
    std::vector<antlr4::tree::TerminalNode *> DECIMAL_LITERAL();
    antlr4::tree::TerminalNode* DECIMAL_LITERAL(size_t i);
    antlr4::tree::TerminalNode *OCTAL_LITERAL();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  FloatingLiteralContext* floatingLiteral();

  class  NumberLiteralContext : public antlr4::ParserRuleContext {
  public:
    NumberLiteralContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    FloatingLiteralContext *floatingLiteral();
    antlr4::tree::TerminalNode *OCTAL_LITERAL();
    antlr4::tree::TerminalNode *DECIMAL_LITERAL();
    antlr4::tree::TerminalNode *HEXADECIMAL_LITERAL();
    antlr4::tree::TerminalNode *INF();
    antlr4::tree::TerminalNode *NAN_SQL();
    antlr4::tree::TerminalNode *PLUS();
    antlr4::tree::TerminalNode *DASH();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  NumberLiteralContext* numberLiteral();

  class  LiteralContext : public antlr4::ParserRuleContext {
  public:
    LiteralContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    NumberLiteralContext *numberLiteral();
    antlr4::tree::TerminalNode *STRING_LITERAL();
    antlr4::tree::TerminalNode *NULL_SQL();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  LiteralContext* literal();

  class  IntervalContext : public antlr4::ParserRuleContext {
  public:
    IntervalContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *SECOND();
    antlr4::tree::TerminalNode *MINUTE();
    antlr4::tree::TerminalNode *HOUR();
    antlr4::tree::TerminalNode *DAY();
    antlr4::tree::TerminalNode *WEEK();
    antlr4::tree::TerminalNode *MONTH();
    antlr4::tree::TerminalNode *QUARTER();
    antlr4::tree::TerminalNode *YEAR();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  IntervalContext* interval();

  class  KeywordContext : public antlr4::ParserRuleContext {
  public:
    KeywordContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *ALL();
    antlr4::tree::TerminalNode *AND();
    antlr4::tree::TerminalNode *ANTI();
    antlr4::tree::TerminalNode *ANY();
    antlr4::tree::TerminalNode *ARRAY();
    antlr4::tree::TerminalNode *AS();
    antlr4::tree::TerminalNode *ASCENDING();
    antlr4::tree::TerminalNode *ASOF();
    antlr4::tree::TerminalNode *BETWEEN();
    antlr4::tree::TerminalNode *BOTH();
    antlr4::tree::TerminalNode *BY();
    antlr4::tree::TerminalNode *CASE();
    antlr4::tree::TerminalNode *CAST();
    antlr4::tree::TerminalNode *COHORT();
    antlr4::tree::TerminalNode *COLLATE();
    antlr4::tree::TerminalNode *COLUMNS();
    antlr4::tree::TerminalNode *CROSS();
    antlr4::tree::TerminalNode *CUBE();
    antlr4::tree::TerminalNode *CURRENT();
    antlr4::tree::TerminalNode *DATE();
    antlr4::tree::TerminalNode *DESC();
    antlr4::tree::TerminalNode *DESCENDING();
    antlr4::tree::TerminalNode *DISTINCT();
    antlr4::tree::TerminalNode *ELSE();
    antlr4::tree::TerminalNode *END();
    antlr4::tree::TerminalNode *EXCLUDE();
    antlr4::tree::TerminalNode *EXTRACT();
    antlr4::tree::TerminalNode *FILTER();
    antlr4::tree::TerminalNode *FINAL();
    antlr4::tree::TerminalNode *FIRST();
    antlr4::tree::TerminalNode *FOR();
    antlr4::tree::TerminalNode *FOLLOWING();
    antlr4::tree::TerminalNode *FROM();
    antlr4::tree::TerminalNode *FULL();
    antlr4::tree::TerminalNode *GROUP();
    antlr4::tree::TerminalNode *HAVING();
    antlr4::tree::TerminalNode *ID();
    antlr4::tree::TerminalNode *IS();
    antlr4::tree::TerminalNode *GROUPING();
    antlr4::tree::TerminalNode *IF();
    antlr4::tree::TerminalNode *IGNORE();
    antlr4::tree::TerminalNode *ILIKE();
    antlr4::tree::TerminalNode *INCLUDE();
    antlr4::tree::TerminalNode *IN();
    antlr4::tree::TerminalNode *INNER();
    antlr4::tree::TerminalNode *INTERVAL();
    antlr4::tree::TerminalNode *JOIN();
    antlr4::tree::TerminalNode *KEY();
    antlr4::tree::TerminalNode *LAMBDA();
    antlr4::tree::TerminalNode *LAST();
    antlr4::tree::TerminalNode *LEADING();
    antlr4::tree::TerminalNode *LEFT();
    antlr4::tree::TerminalNode *LIKE();
    antlr4::tree::TerminalNode *LIMIT();
    antlr4::tree::TerminalNode *NAME();
    antlr4::tree::TerminalNode *NATURAL();
    antlr4::tree::TerminalNode *NOT();
    antlr4::tree::TerminalNode *NULLS();
    antlr4::tree::TerminalNode *OFFSET();
    antlr4::tree::TerminalNode *ON();
    antlr4::tree::TerminalNode *OR();
    antlr4::tree::TerminalNode *ORDER();
    antlr4::tree::TerminalNode *OUTER();
    antlr4::tree::TerminalNode *OVER();
    antlr4::tree::TerminalNode *PARTITION();
    antlr4::tree::TerminalNode *PIVOT();
    antlr4::tree::TerminalNode *POSITIONAL();
    antlr4::tree::TerminalNode *PRECEDING();
    antlr4::tree::TerminalNode *PREWHERE();
    antlr4::tree::TerminalNode *QUALIFY();
    antlr4::tree::TerminalNode *RANGE();
    antlr4::tree::TerminalNode *RECURSIVE();
    antlr4::tree::TerminalNode *REPLACE();
    antlr4::tree::TerminalNode *RETURN();
    antlr4::tree::TerminalNode *RIGHT();
    antlr4::tree::TerminalNode *ROLLUP();
    antlr4::tree::TerminalNode *ROW();
    antlr4::tree::TerminalNode *ROWS();
    antlr4::tree::TerminalNode *SAMPLE();
    antlr4::tree::TerminalNode *SELECT();
    antlr4::tree::TerminalNode *SEMI();
    antlr4::tree::TerminalNode *SETS();
    antlr4::tree::TerminalNode *SETTINGS();
    antlr4::tree::TerminalNode *SUBSTRING();
    antlr4::tree::TerminalNode *THEN();
    antlr4::tree::TerminalNode *TIES();
    antlr4::tree::TerminalNode *TIMESTAMP();
    antlr4::tree::TerminalNode *TOTALS();
    antlr4::tree::TerminalNode *TRAILING();
    antlr4::tree::TerminalNode *TRIM();
    antlr4::tree::TerminalNode *TRUNCATE();
    antlr4::tree::TerminalNode *TRY_CAST();
    antlr4::tree::TerminalNode *TO();
    antlr4::tree::TerminalNode *TOP();
    antlr4::tree::TerminalNode *UNBOUNDED();
    antlr4::tree::TerminalNode *UNION();
    antlr4::tree::TerminalNode *UNPIVOT();
    antlr4::tree::TerminalNode *USING();
    antlr4::tree::TerminalNode *VALUES();
    antlr4::tree::TerminalNode *WHEN();
    antlr4::tree::TerminalNode *WHERE();
    antlr4::tree::TerminalNode *WINDOW();
    antlr4::tree::TerminalNode *WITH();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  KeywordContext* keyword();

  class  KeywordForAliasContext : public antlr4::ParserRuleContext {
  public:
    KeywordForAliasContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *DATE();
    antlr4::tree::TerminalNode *FIRST();
    antlr4::tree::TerminalNode *ID();
    antlr4::tree::TerminalNode *KEY();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  KeywordForAliasContext* keywordForAlias();

  class  AliasContext : public antlr4::ParserRuleContext {
  public:
    AliasContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *IDENTIFIER();
    KeywordForAliasContext *keywordForAlias();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  AliasContext* alias();

  class  IdentifierContext : public antlr4::ParserRuleContext {
  public:
    IdentifierContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *IDENTIFIER();
    IntervalContext *interval();
    KeywordContext *keyword();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  IdentifierContext* identifier();

  class  EnumValueContext : public antlr4::ParserRuleContext {
  public:
    EnumValueContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    StringContext *string();
    antlr4::tree::TerminalNode *EQ_SINGLE();
    NumberLiteralContext *numberLiteral();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  EnumValueContext* enumValue();

  class  PlaceholderContext : public antlr4::ParserRuleContext {
  public:
    PlaceholderContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *LBRACE();
    ColumnExprContext *columnExpr();
    antlr4::tree::TerminalNode *RBRACE();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  PlaceholderContext* placeholder();

  class  StringContext : public antlr4::ParserRuleContext {
  public:
    StringContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *STRING_LITERAL();
    TemplateStringContext *templateString();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  StringContext* string();

  class  TemplateStringContext : public antlr4::ParserRuleContext {
  public:
    TemplateStringContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *QUOTE_SINGLE_TEMPLATE();
    antlr4::tree::TerminalNode *QUOTE_SINGLE();
    std::vector<StringContentsContext *> stringContents();
    StringContentsContext* stringContents(size_t i);


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  TemplateStringContext* templateString();

  class  StringContentsContext : public antlr4::ParserRuleContext {
  public:
    StringContentsContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *STRING_ESCAPE_TRIGGER();
    ColumnExprContext *columnExpr();
    antlr4::tree::TerminalNode *RBRACE();
    antlr4::tree::TerminalNode *STRING_TEXT();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  StringContentsContext* stringContents();

  class  FullTemplateStringContext : public antlr4::ParserRuleContext {
  public:
    FullTemplateStringContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *QUOTE_SINGLE_TEMPLATE_FULL();
    antlr4::tree::TerminalNode *EOF();
    std::vector<StringContentsFullContext *> stringContentsFull();
    StringContentsFullContext* stringContentsFull(size_t i);


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  FullTemplateStringContext* fullTemplateString();

  class  StringContentsFullContext : public antlr4::ParserRuleContext {
  public:
    StringContentsFullContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *FULL_STRING_ESCAPE_TRIGGER();
    ColumnExprContext *columnExpr();
    antlr4::tree::TerminalNode *RBRACE();
    antlr4::tree::TerminalNode *FULL_STRING_TEXT();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  StringContentsFullContext* stringContentsFull();


  bool sempred(antlr4::RuleContext *_localctx, size_t ruleIndex, size_t predicateIndex) override;

  bool joinExprSempred(JoinExprContext *_localctx, size_t predicateIndex);
  bool columnTypeExprSempred(ColumnTypeExprContext *_localctx, size_t predicateIndex);
  bool columnExprSempred(ColumnExprContext *_localctx, size_t predicateIndex);
  bool tableExprSempred(TableExprContext *_localctx, size_t predicateIndex);

  // By default the static state used to implement the parser is lazily initialized during the first
  // call to the constructor. You can call this function if you wish to initialize the static state
  // ahead of time.
  static void initialize();

private:
};

