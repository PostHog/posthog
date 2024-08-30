
// Generated from HogQLLexer.g4 by ANTLR 4.13.2

#pragma once


#include "antlr4-runtime.h"




class  HogQLLexer : public antlr4::Lexer {
public:
  enum {
    ALL = 1, AND = 2, ANTI = 3, ANY = 4, ARRAY = 5, AS = 6, ASCENDING = 7, 
    ASOF = 8, BETWEEN = 9, BOTH = 10, BY = 11, CASE = 12, CAST = 13, CATCH = 14, 
    COHORT = 15, COLLATE = 16, CROSS = 17, CUBE = 18, CURRENT = 19, DATE = 20, 
    DAY = 21, DESC = 22, DESCENDING = 23, DISTINCT = 24, ELSE = 25, END = 26, 
    EXTRACT = 27, FINAL = 28, FINALLY = 29, FIRST = 30, FN = 31, FOLLOWING = 32, 
    FOR = 33, FROM = 34, FULL = 35, FUN = 36, GROUP = 37, HAVING = 38, HOUR = 39, 
    ID = 40, IF = 41, ILIKE = 42, IN = 43, INF = 44, INNER = 45, INTERVAL = 46, 
    IS = 47, JOIN = 48, KEY = 49, LAST = 50, LEADING = 51, LEFT = 52, LET = 53, 
    LIKE = 54, LIMIT = 55, MINUTE = 56, MONTH = 57, NAN_SQL = 58, NOT = 59, 
    NULL_SQL = 60, NULLS = 61, OFFSET = 62, ON = 63, OR = 64, ORDER = 65, 
    OUTER = 66, OVER = 67, PARTITION = 68, PRECEDING = 69, PREWHERE = 70, 
    QUARTER = 71, RANGE = 72, RETURN = 73, RIGHT = 74, ROLLUP = 75, ROW = 76, 
    ROWS = 77, SAMPLE = 78, SECOND = 79, SELECT = 80, SEMI = 81, SETTINGS = 82, 
    SUBSTRING = 83, THEN = 84, THROW = 85, TIES = 86, TIMESTAMP = 87, TO = 88, 
    TOP = 89, TOTALS = 90, TRAILING = 91, TRIM = 92, TRUNCATE = 93, TRY = 94, 
    UNBOUNDED = 95, UNION = 96, USING = 97, WEEK = 98, WHEN = 99, WHERE = 100, 
    WHILE = 101, WINDOW = 102, WITH = 103, YEAR = 104, ESCAPE_CHAR_COMMON = 105, 
    IDENTIFIER = 106, FLOATING_LITERAL = 107, OCTAL_LITERAL = 108, DECIMAL_LITERAL = 109, 
    HEXADECIMAL_LITERAL = 110, STRING_LITERAL = 111, ARROW = 112, ASTERISK = 113, 
    BACKQUOTE = 114, BACKSLASH = 115, COLON = 116, COMMA = 117, CONCAT = 118, 
    DASH = 119, DOLLAR = 120, DOT = 121, EQ_DOUBLE = 122, EQ_SINGLE = 123, 
    GT_EQ = 124, GT = 125, HASH = 126, IREGEX_SINGLE = 127, IREGEX_DOUBLE = 128, 
    LBRACE = 129, LBRACKET = 130, LPAREN = 131, LT_EQ = 132, LT = 133, NOT_EQ = 134, 
    NOT_IREGEX = 135, NOT_REGEX = 136, NULL_PROPERTY = 137, NULLISH = 138, 
    PERCENT = 139, PLUS = 140, QUERY = 141, QUOTE_DOUBLE = 142, QUOTE_SINGLE_TEMPLATE = 143, 
    QUOTE_SINGLE_TEMPLATE_FULL = 144, QUOTE_SINGLE = 145, REGEX_SINGLE = 146, 
    REGEX_DOUBLE = 147, RBRACE = 148, RBRACKET = 149, RPAREN = 150, SEMICOLON = 151, 
    SLASH = 152, UNDERSCORE = 153, MULTI_LINE_COMMENT = 154, SINGLE_LINE_COMMENT = 155, 
    WHITESPACE = 156, STRING_TEXT = 157, STRING_ESCAPE_TRIGGER = 158, FULL_STRING_TEXT = 159, 
    FULL_STRING_ESCAPE_TRIGGER = 160
  };

  enum {
    IN_TEMPLATE_STRING = 1, IN_FULL_TEMPLATE_STRING = 2
  };

  explicit HogQLLexer(antlr4::CharStream *input);

  ~HogQLLexer() override;


  std::string getGrammarFileName() const override;

  const std::vector<std::string>& getRuleNames() const override;

  const std::vector<std::string>& getChannelNames() const override;

  const std::vector<std::string>& getModeNames() const override;

  const antlr4::dfa::Vocabulary& getVocabulary() const override;

  antlr4::atn::SerializedATNView getSerializedATN() const override;

  const antlr4::atn::ATN& getATN() const override;

  // By default the static state used to implement the lexer is lazily initialized during the first
  // call to the constructor. You can call this function if you wish to initialize the static state
  // ahead of time.
  static void initialize();

private:

  // Individual action functions triggered by action() above.

  // Individual semantic predicate functions triggered by sempred() above.

};

