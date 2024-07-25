
// Generated from HogQLParser.g4 by ANTLR 4.13.1

#pragma once


#include "antlr4-runtime.h"




class  HogQLParser : public antlr4::Parser {
public:
  enum {
    ALL = 1, AND = 2, ANTI = 3, ANY = 4, ARRAY = 5, AS = 6, ASCENDING = 7, 
    ASOF = 8, BETWEEN = 9, BOTH = 10, BY = 11, CASE = 12, CAST = 13, CATCH = 14, 
    COHORT = 15, COLLATE = 16, CROSS = 17, CUBE = 18, CURRENT = 19, DATE = 20, 
    DAY = 21, DESC = 22, DESCENDING = 23, DISTINCT = 24, ELSE = 25, END = 26, 
    EXTRACT = 27, FINAL = 28, FINALLY = 29, FIRST = 30, FN = 31, FOLLOWING = 32, 
    FOR = 33, FROM = 34, FULL = 35, GROUP = 36, HAVING = 37, HOUR = 38, 
    ID = 39, IF = 40, ILIKE = 41, IN = 42, INF = 43, INNER = 44, INTERVAL = 45, 
    IS = 46, JOIN = 47, KEY = 48, LAST = 49, LEADING = 50, LEFT = 51, LET = 52, 
    LIKE = 53, LIMIT = 54, MINUTE = 55, MONTH = 56, NAN_SQL = 57, NOT = 58, 
    NULL_SQL = 59, NULLS = 60, OFFSET = 61, ON = 62, OR = 63, ORDER = 64, 
    OUTER = 65, OVER = 66, PARTITION = 67, PRECEDING = 68, PREWHERE = 69, 
    QUARTER = 70, RANGE = 71, RETURN = 72, RIGHT = 73, ROLLUP = 74, ROW = 75, 
    ROWS = 76, SAMPLE = 77, SECOND = 78, SELECT = 79, SEMI = 80, SETTINGS = 81, 
    SUBSTRING = 82, THEN = 83, THROW = 84, TIES = 85, TIMESTAMP = 86, TO = 87, 
    TOP = 88, TOTALS = 89, TRAILING = 90, TRIM = 91, TRUNCATE = 92, TRY = 93, 
    UNBOUNDED = 94, UNION = 95, USING = 96, WEEK = 97, WHEN = 98, WHERE = 99, 
    WHILE = 100, WINDOW = 101, WITH = 102, YEAR = 103, ESCAPE_CHAR_COMMON = 104, 
    IDENTIFIER = 105, FLOATING_LITERAL = 106, OCTAL_LITERAL = 107, DECIMAL_LITERAL = 108, 
    HEXADECIMAL_LITERAL = 109, STRING_LITERAL = 110, ARROW = 111, ASTERISK = 112, 
    BACKQUOTE = 113, BACKSLASH = 114, COLON = 115, COMMA = 116, CONCAT = 117, 
    DASH = 118, DOLLAR = 119, DOT = 120, EQ_DOUBLE = 121, EQ_SINGLE = 122, 
    GT_EQ = 123, GT = 124, HASH = 125, IREGEX_SINGLE = 126, IREGEX_DOUBLE = 127, 
    LBRACE = 128, LBRACKET = 129, LPAREN = 130, LT_EQ = 131, LT = 132, NOT_EQ = 133, 
    NOT_IREGEX = 134, NOT_REGEX = 135, NULL_PROPERTY = 136, NULLISH = 137, 
    PERCENT = 138, PLUS = 139, QUERY = 140, QUOTE_DOUBLE = 141, QUOTE_SINGLE_TEMPLATE = 142, 
    QUOTE_SINGLE_TEMPLATE_FULL = 143, QUOTE_SINGLE = 144, REGEX_SINGLE = 145, 
    REGEX_DOUBLE = 146, RBRACE = 147, RBRACKET = 148, RPAREN = 149, SEMICOLON = 150, 
    SLASH = 151, UNDERSCORE = 152, MULTI_LINE_COMMENT = 153, SINGLE_LINE_COMMENT = 154, 
    WHITESPACE = 155, STRING_TEXT = 156, STRING_ESCAPE_TRIGGER = 157, FULL_STRING_TEXT = 158, 
    FULL_STRING_ESCAPE_TRIGGER = 159
  };

  enum {
    RuleProgram = 0, RuleDeclaration = 1, RuleExpression = 2, RuleVarDecl = 3, 
    RuleIdentifierList = 4, RuleStatement = 5, RuleReturnStmt = 6, RuleThrowStmt = 7, 
    RuleCatchBlock = 8, RuleTryCatchStmt = 9, RuleIfStmt = 10, RuleWhileStmt = 11, 
    RuleForStmt = 12, RuleForInStmt = 13, RuleFuncStmt = 14, RuleVarAssignment = 15, 
    RuleExprStmt = 16, RuleEmptyStmt = 17, RuleBlock = 18, RuleKvPair = 19, 
    RuleKvPairList = 20, RuleSelect = 21, RuleSelectUnionStmt = 22, RuleSelectStmtWithParens = 23, 
    RuleSelectStmt = 24, RuleWithClause = 25, RuleTopClause = 26, RuleFromClause = 27, 
    RuleArrayJoinClause = 28, RuleWindowClause = 29, RulePrewhereClause = 30, 
    RuleWhereClause = 31, RuleGroupByClause = 32, RuleHavingClause = 33, 
    RuleOrderByClause = 34, RuleProjectionOrderByClause = 35, RuleLimitAndOffsetClause = 36, 
    RuleOffsetOnlyClause = 37, RuleSettingsClause = 38, RuleJoinExpr = 39, 
    RuleJoinOp = 40, RuleJoinOpCross = 41, RuleJoinConstraintClause = 42, 
    RuleSampleClause = 43, RuleOrderExprList = 44, RuleOrderExpr = 45, RuleRatioExpr = 46, 
    RuleSettingExprList = 47, RuleSettingExpr = 48, RuleWindowExpr = 49, 
    RuleWinPartitionByClause = 50, RuleWinOrderByClause = 51, RuleWinFrameClause = 52, 
    RuleWinFrameExtend = 53, RuleWinFrameBound = 54, RuleExpr = 55, RuleColumnTypeExpr = 56, 
    RuleColumnExprList = 57, RuleColumnExpr = 58, RuleColumnArgList = 59, 
    RuleColumnArgExpr = 60, RuleColumnLambdaExpr = 61, RuleHogqlxTagElement = 62, 
    RuleHogqlxTagAttribute = 63, RuleWithExprList = 64, RuleWithExpr = 65, 
    RuleColumnIdentifier = 66, RuleNestedIdentifier = 67, RuleTableExpr = 68, 
    RuleTableFunctionExpr = 69, RuleTableIdentifier = 70, RuleTableArgList = 71, 
    RuleDatabaseIdentifier = 72, RuleFloatingLiteral = 73, RuleNumberLiteral = 74, 
    RuleLiteral = 75, RuleInterval = 76, RuleKeyword = 77, RuleKeywordForAlias = 78, 
    RuleAlias = 79, RuleIdentifier = 80, RuleEnumValue = 81, RulePlaceholder = 82, 
    RuleString = 83, RuleTemplateString = 84, RuleStringContents = 85, RuleFullTemplateString = 86, 
    RuleStringContentsFull = 87
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
  class SelectUnionStmtContext;
  class SelectStmtWithParensContext;
  class SelectStmtContext;
  class WithClauseContext;
  class TopClauseContext;
  class FromClauseContext;
  class ArrayJoinClauseContext;
  class WindowClauseContext;
  class PrewhereClauseContext;
  class WhereClauseContext;
  class GroupByClauseContext;
  class HavingClauseContext;
  class OrderByClauseContext;
  class ProjectionOrderByClauseContext;
  class LimitAndOffsetClauseContext;
  class OffsetOnlyClauseContext;
  class SettingsClauseContext;
  class JoinExprContext;
  class JoinOpContext;
  class JoinOpCrossContext;
  class JoinConstraintClauseContext;
  class SampleClauseContext;
  class OrderExprListContext;
  class OrderExprContext;
  class RatioExprContext;
  class SettingExprListContext;
  class SettingExprContext;
  class WindowExprContext;
  class WinPartitionByClauseContext;
  class WinOrderByClauseContext;
  class WinFrameClauseContext;
  class WinFrameExtendContext;
  class WinFrameBoundContext;
  class ExprContext;
  class ColumnTypeExprContext;
  class ColumnExprListContext;
  class ColumnExprContext;
  class ColumnArgListContext;
  class ColumnArgExprContext;
  class ColumnLambdaExprContext;
  class HogqlxTagElementContext;
  class HogqlxTagAttributeContext;
  class WithExprListContext;
  class WithExprContext;
  class ColumnIdentifierContext;
  class NestedIdentifierContext;
  class TableExprContext;
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
    antlr4::tree::TerminalNode *COLON();
    antlr4::tree::TerminalNode *EQ_SINGLE();
    ExpressionContext *expression();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  VarDeclContext* varDecl();

  class  IdentifierListContext : public antlr4::ParserRuleContext {
  public:
    IdentifierListContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    std::vector<IdentifierContext *> identifier();
    IdentifierContext* identifier(size_t i);
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
    antlr4::tree::TerminalNode *FN();
    IdentifierContext *identifier();
    antlr4::tree::TerminalNode *LPAREN();
    antlr4::tree::TerminalNode *RPAREN();
    BlockContext *block();
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
    antlr4::tree::TerminalNode *COLON();
    antlr4::tree::TerminalNode *EQ_SINGLE();


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
    SelectUnionStmtContext *selectUnionStmt();
    SelectStmtContext *selectStmt();
    HogqlxTagElementContext *hogqlxTagElement();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  SelectContext* select();

  class  SelectUnionStmtContext : public antlr4::ParserRuleContext {
  public:
    SelectUnionStmtContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    std::vector<SelectStmtWithParensContext *> selectStmtWithParens();
    SelectStmtWithParensContext* selectStmtWithParens(size_t i);
    std::vector<antlr4::tree::TerminalNode *> UNION();
    antlr4::tree::TerminalNode* UNION(size_t i);
    std::vector<antlr4::tree::TerminalNode *> ALL();
    antlr4::tree::TerminalNode* ALL(size_t i);


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  SelectUnionStmtContext* selectUnionStmt();

  class  SelectStmtWithParensContext : public antlr4::ParserRuleContext {
  public:
    SelectStmtWithParensContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    SelectStmtContext *selectStmt();
    antlr4::tree::TerminalNode *LPAREN();
    SelectUnionStmtContext *selectUnionStmt();
    antlr4::tree::TerminalNode *RPAREN();
    PlaceholderContext *placeholder();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  SelectStmtWithParensContext* selectStmtWithParens();

  class  SelectStmtContext : public antlr4::ParserRuleContext {
  public:
    HogQLParser::WithClauseContext *with = nullptr;
    HogQLParser::ColumnExprListContext *columns = nullptr;
    HogQLParser::FromClauseContext *from = nullptr;
    HogQLParser::WhereClauseContext *where = nullptr;
    SelectStmtContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *SELECT();
    ColumnExprListContext *columnExprList();
    antlr4::tree::TerminalNode *DISTINCT();
    TopClauseContext *topClause();
    ArrayJoinClauseContext *arrayJoinClause();
    PrewhereClauseContext *prewhereClause();
    GroupByClauseContext *groupByClause();
    std::vector<antlr4::tree::TerminalNode *> WITH();
    antlr4::tree::TerminalNode* WITH(size_t i);
    antlr4::tree::TerminalNode *TOTALS();
    HavingClauseContext *havingClause();
    WindowClauseContext *windowClause();
    OrderByClauseContext *orderByClause();
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
    antlr4::tree::TerminalNode *LPAREN();
    ColumnExprListContext *columnExprList();
    antlr4::tree::TerminalNode *RPAREN();
    antlr4::tree::TerminalNode *CUBE();
    antlr4::tree::TerminalNode *ROLLUP();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  GroupByClauseContext* groupByClause();

  class  HavingClauseContext : public antlr4::ParserRuleContext {
  public:
    HavingClauseContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *HAVING();
    ColumnExprContext *columnExpr();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  HavingClauseContext* havingClause();

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

  class  LimitAndOffsetClauseContext : public antlr4::ParserRuleContext {
  public:
    LimitAndOffsetClauseContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *LIMIT();
    std::vector<ColumnExprContext *> columnExpr();
    ColumnExprContext* columnExpr(size_t i);
    antlr4::tree::TerminalNode *COMMA();
    antlr4::tree::TerminalNode *BY();
    ColumnExprListContext *columnExprList();
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

  class  JoinExprContext : public antlr4::ParserRuleContext {
  public:
    JoinExprContext(antlr4::ParserRuleContext *parent, size_t invokingState);
   
    JoinExprContext() = default;
    void copyFrom(JoinExprContext *context);
    using antlr4::ParserRuleContext::copyFrom;

    virtual size_t getRuleIndex() const override;

   
  };

  class  JoinExprOpContext : public JoinExprContext {
  public:
    JoinExprOpContext(JoinExprContext *ctx);

    std::vector<JoinExprContext *> joinExpr();
    JoinExprContext* joinExpr(size_t i);
    antlr4::tree::TerminalNode *JOIN();
    JoinConstraintClauseContext *joinConstraintClause();
    JoinOpContext *joinOp();

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

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  JoinOpInnerContext : public JoinOpContext {
  public:
    JoinOpInnerContext(JoinOpContext *ctx);

    antlr4::tree::TerminalNode *INNER();
    antlr4::tree::TerminalNode *ALL();
    antlr4::tree::TerminalNode *ANY();
    antlr4::tree::TerminalNode *ASOF();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  JoinOpLeftRightContext : public JoinOpContext {
  public:
    JoinOpLeftRightContext(JoinOpContext *ctx);

    antlr4::tree::TerminalNode *LEFT();
    antlr4::tree::TerminalNode *RIGHT();
    antlr4::tree::TerminalNode *OUTER();
    antlr4::tree::TerminalNode *SEMI();
    antlr4::tree::TerminalNode *ALL();
    antlr4::tree::TerminalNode *ANTI();
    antlr4::tree::TerminalNode *ANY();
    antlr4::tree::TerminalNode *ASOF();

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
    antlr4::tree::TerminalNode *OFFSET();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  SampleClauseContext* sampleClause();

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
    NumberLiteralContext *numberLiteral();


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

  class  ColumnTypeExprSimpleContext : public ColumnTypeExprContext {
  public:
    ColumnTypeExprSimpleContext(ColumnTypeExprContext *ctx);

    IdentifierContext *identifier();

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

  ColumnTypeExprContext* columnTypeExpr();

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

  class  ColumnExprContext : public antlr4::ParserRuleContext {
  public:
    ColumnExprContext(antlr4::ParserRuleContext *parent, size_t invokingState);
   
    ColumnExprContext() = default;
    void copyFrom(ColumnExprContext *context);
    using antlr4::ParserRuleContext::copyFrom;

    virtual size_t getRuleIndex() const override;

   
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
    SelectUnionStmtContext *selectUnionStmt();
    antlr4::tree::TerminalNode *RPAREN();

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
    ColumnExprListContext *columnExprList();

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

  class  ColumnExprOrContext : public ColumnExprContext {
  public:
    ColumnExprOrContext(ColumnExprContext *ctx);

    std::vector<ColumnExprContext *> columnExpr();
    ColumnExprContext* columnExpr(size_t i);
    antlr4::tree::TerminalNode *OR();

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

    std::vector<IdentifierContext *> identifier();
    IdentifierContext* identifier(size_t i);
    antlr4::tree::TerminalNode *OVER();
    std::vector<antlr4::tree::TerminalNode *> LPAREN();
    antlr4::tree::TerminalNode* LPAREN(size_t i);
    std::vector<antlr4::tree::TerminalNode *> RPAREN();
    antlr4::tree::TerminalNode* RPAREN(size_t i);
    ColumnExprListContext *columnExprList();
    antlr4::tree::TerminalNode *DISTINCT();
    ColumnArgListContext *columnArgList();

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

  class  ColumnExprTagElementContext : public ColumnExprContext {
  public:
    ColumnExprTagElementContext(ColumnExprContext *ctx);

    HogqlxTagElementContext *hogqlxTagElement();

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

  class  ColumnExprPropertyAccessContext : public ColumnExprContext {
  public:
    ColumnExprPropertyAccessContext(ColumnExprContext *ctx);

    ColumnExprContext *columnExpr();
    antlr4::tree::TerminalNode *DOT();
    IdentifierContext *identifier();

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

  class  ColumnExprTimestampContext : public ColumnExprContext {
  public:
    ColumnExprTimestampContext(ColumnExprContext *ctx);

    antlr4::tree::TerminalNode *TIMESTAMP();
    antlr4::tree::TerminalNode *STRING_LITERAL();

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

  class  ColumnExprAndContext : public ColumnExprContext {
  public:
    ColumnExprAndContext(ColumnExprContext *ctx);

    std::vector<ColumnExprContext *> columnExpr();
    ColumnExprContext* columnExpr(size_t i);
    antlr4::tree::TerminalNode *AND();

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

  class  ColumnExprNotContext : public ColumnExprContext {
  public:
    ColumnExprNotContext(ColumnExprContext *ctx);

    antlr4::tree::TerminalNode *NOT();
    ColumnExprContext *columnExpr();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprWinFunctionContext : public ColumnExprContext {
  public:
    ColumnExprWinFunctionContext(ColumnExprContext *ctx);

    IdentifierContext *identifier();
    antlr4::tree::TerminalNode *OVER();
    std::vector<antlr4::tree::TerminalNode *> LPAREN();
    antlr4::tree::TerminalNode* LPAREN(size_t i);
    WindowExprContext *windowExpr();
    std::vector<antlr4::tree::TerminalNode *> RPAREN();
    antlr4::tree::TerminalNode* RPAREN(size_t i);
    ColumnExprListContext *columnExprList();
    antlr4::tree::TerminalNode *DISTINCT();
    ColumnArgListContext *columnArgList();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprIdentifierContext : public ColumnExprContext {
  public:
    ColumnExprIdentifierContext(ColumnExprContext *ctx);

    ColumnIdentifierContext *columnIdentifier();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprFunctionContext : public ColumnExprContext {
  public:
    ColumnExprFunctionContext(ColumnExprContext *ctx);

    IdentifierContext *identifier();
    std::vector<antlr4::tree::TerminalNode *> LPAREN();
    antlr4::tree::TerminalNode* LPAREN(size_t i);
    std::vector<antlr4::tree::TerminalNode *> RPAREN();
    antlr4::tree::TerminalNode* RPAREN(size_t i);
    antlr4::tree::TerminalNode *DISTINCT();
    ColumnArgListContext *columnArgList();
    ColumnExprListContext *columnExprList();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  ColumnExprAsteriskContext : public ColumnExprContext {
  public:
    ColumnExprAsteriskContext(ColumnExprContext *ctx);

    antlr4::tree::TerminalNode *ASTERISK();
    TableIdentifierContext *tableIdentifier();
    antlr4::tree::TerminalNode *DOT();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  ColumnExprContext* columnExpr();
  ColumnExprContext* columnExpr(int precedence);
  class  ColumnArgListContext : public antlr4::ParserRuleContext {
  public:
    ColumnArgListContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    std::vector<ColumnArgExprContext *> columnArgExpr();
    ColumnArgExprContext* columnArgExpr(size_t i);
    std::vector<antlr4::tree::TerminalNode *> COMMA();
    antlr4::tree::TerminalNode* COMMA(size_t i);


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  ColumnArgListContext* columnArgList();

  class  ColumnArgExprContext : public antlr4::ParserRuleContext {
  public:
    ColumnArgExprContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    ColumnLambdaExprContext *columnLambdaExpr();
    ColumnExprContext *columnExpr();


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  ColumnArgExprContext* columnArgExpr();

  class  ColumnLambdaExprContext : public antlr4::ParserRuleContext {
  public:
    ColumnLambdaExprContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *ARROW();
    ColumnExprContext *columnExpr();
    antlr4::tree::TerminalNode *LPAREN();
    std::vector<IdentifierContext *> identifier();
    IdentifierContext* identifier(size_t i);
    antlr4::tree::TerminalNode *RPAREN();
    std::vector<antlr4::tree::TerminalNode *> COMMA();
    antlr4::tree::TerminalNode* COMMA(size_t i);


    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  ColumnLambdaExprContext* columnLambdaExpr();

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
    antlr4::tree::TerminalNode *SLASH();
    antlr4::tree::TerminalNode *GT();
    std::vector<HogqlxTagAttributeContext *> hogqlxTagAttribute();
    HogqlxTagAttributeContext* hogqlxTagAttribute(size_t i);

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  HogqlxTagElementNestedContext : public HogqlxTagElementContext {
  public:
    HogqlxTagElementNestedContext(HogqlxTagElementContext *ctx);

    std::vector<antlr4::tree::TerminalNode *> LT();
    antlr4::tree::TerminalNode* LT(size_t i);
    std::vector<IdentifierContext *> identifier();
    IdentifierContext* identifier(size_t i);
    std::vector<antlr4::tree::TerminalNode *> GT();
    antlr4::tree::TerminalNode* GT(size_t i);
    antlr4::tree::TerminalNode *SLASH();
    std::vector<HogqlxTagAttributeContext *> hogqlxTagAttribute();
    HogqlxTagAttributeContext* hogqlxTagAttribute(size_t i);
    HogqlxTagElementContext *hogqlxTagElement();

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
    SelectUnionStmtContext *selectUnionStmt();
    antlr4::tree::TerminalNode *RPAREN();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  WithExprContext* withExpr();

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
    SelectUnionStmtContext *selectUnionStmt();
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

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  class  TableExprFunctionContext : public TableExprContext {
  public:
    TableExprFunctionContext(TableExprContext *ctx);

    TableFunctionExprContext *tableFunctionExpr();

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
  };

  TableExprContext* tableExpr();
  TableExprContext* tableExpr(int precedence);
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
    IdentifierContext *identifier();
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
    antlr4::tree::TerminalNode *CROSS();
    antlr4::tree::TerminalNode *CUBE();
    antlr4::tree::TerminalNode *CURRENT();
    antlr4::tree::TerminalNode *DATE();
    antlr4::tree::TerminalNode *DESC();
    antlr4::tree::TerminalNode *DESCENDING();
    antlr4::tree::TerminalNode *DISTINCT();
    antlr4::tree::TerminalNode *ELSE();
    antlr4::tree::TerminalNode *END();
    antlr4::tree::TerminalNode *EXTRACT();
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
    antlr4::tree::TerminalNode *IF();
    antlr4::tree::TerminalNode *ILIKE();
    antlr4::tree::TerminalNode *IN();
    antlr4::tree::TerminalNode *INNER();
    antlr4::tree::TerminalNode *INTERVAL();
    antlr4::tree::TerminalNode *JOIN();
    antlr4::tree::TerminalNode *KEY();
    antlr4::tree::TerminalNode *LAST();
    antlr4::tree::TerminalNode *LEADING();
    antlr4::tree::TerminalNode *LEFT();
    antlr4::tree::TerminalNode *LIKE();
    antlr4::tree::TerminalNode *LIMIT();
    antlr4::tree::TerminalNode *NOT();
    antlr4::tree::TerminalNode *NULLS();
    antlr4::tree::TerminalNode *OFFSET();
    antlr4::tree::TerminalNode *ON();
    antlr4::tree::TerminalNode *OR();
    antlr4::tree::TerminalNode *ORDER();
    antlr4::tree::TerminalNode *OUTER();
    antlr4::tree::TerminalNode *OVER();
    antlr4::tree::TerminalNode *PARTITION();
    antlr4::tree::TerminalNode *PRECEDING();
    antlr4::tree::TerminalNode *PREWHERE();
    antlr4::tree::TerminalNode *RANGE();
    antlr4::tree::TerminalNode *RETURN();
    antlr4::tree::TerminalNode *RIGHT();
    antlr4::tree::TerminalNode *ROLLUP();
    antlr4::tree::TerminalNode *ROW();
    antlr4::tree::TerminalNode *ROWS();
    antlr4::tree::TerminalNode *SAMPLE();
    antlr4::tree::TerminalNode *SELECT();
    antlr4::tree::TerminalNode *SEMI();
    antlr4::tree::TerminalNode *SETTINGS();
    antlr4::tree::TerminalNode *SUBSTRING();
    antlr4::tree::TerminalNode *THEN();
    antlr4::tree::TerminalNode *TIES();
    antlr4::tree::TerminalNode *TIMESTAMP();
    antlr4::tree::TerminalNode *TOTALS();
    antlr4::tree::TerminalNode *TRAILING();
    antlr4::tree::TerminalNode *TRIM();
    antlr4::tree::TerminalNode *TRUNCATE();
    antlr4::tree::TerminalNode *TO();
    antlr4::tree::TerminalNode *TOP();
    antlr4::tree::TerminalNode *UNBOUNDED();
    antlr4::tree::TerminalNode *UNION();
    antlr4::tree::TerminalNode *USING();
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
    IdentifierContext *identifier();
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
  bool columnExprSempred(ColumnExprContext *_localctx, size_t predicateIndex);
  bool tableExprSempred(TableExprContext *_localctx, size_t predicateIndex);

  // By default the static state used to implement the parser is lazily initialized during the first
  // call to the constructor. You can call this function if you wish to initialize the static state
  // ahead of time.
  static void initialize();

private:
};

