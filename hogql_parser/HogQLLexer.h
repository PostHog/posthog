
// Generated from HogQLLexer.g4 by ANTLR 4.13.1

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

