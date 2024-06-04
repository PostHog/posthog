
// Generated from HogQLLexer.g4 by ANTLR 4.13.1

#pragma once


#include "antlr4-runtime.h"




class  HogQLLexer : public antlr4::Lexer {
public:
  enum {
    ALL = 1, AND = 2, ANTI = 3, ANY = 4, ARRAY = 5, AS = 6, ASCENDING = 7, 
    ASOF = 8, BETWEEN = 9, BOTH = 10, BY = 11, CASE = 12, CAST = 13, COHORT = 14, 
    COLLATE = 15, CROSS = 16, CUBE = 17, CURRENT = 18, DATE = 19, DAY = 20, 
    DESC = 21, DESCENDING = 22, DISTINCT = 23, ELSE = 24, END = 25, EXTRACT = 26, 
    FINAL = 27, FIRST = 28, FN = 29, FOLLOWING = 30, FOR = 31, FROM = 32, 
    FULL = 33, GROUP = 34, HAVING = 35, HOUR = 36, ID = 37, IF = 38, ILIKE = 39, 
    IN = 40, INF = 41, INNER = 42, INTERVAL = 43, IS = 44, JOIN = 45, KEY = 46, 
    LAST = 47, LEADING = 48, LEFT = 49, LET = 50, LIKE = 51, LIMIT = 52, 
    MINUTE = 53, MONTH = 54, NAN_SQL = 55, NOT = 56, NULL_SQL = 57, NULLS = 58, 
    OFFSET = 59, ON = 60, OR = 61, ORDER = 62, OUTER = 63, OVER = 64, PARTITION = 65, 
    PRECEDING = 66, PREWHERE = 67, QUARTER = 68, RANGE = 69, RETURN = 70, 
    RIGHT = 71, ROLLUP = 72, ROW = 73, ROWS = 74, SAMPLE = 75, SECOND = 76, 
    SELECT = 77, SEMI = 78, SETTINGS = 79, SUBSTRING = 80, THEN = 81, TIES = 82, 
    TIMESTAMP = 83, TO = 84, TOP = 85, TOTALS = 86, TRAILING = 87, TRIM = 88, 
    TRUNCATE = 89, UNBOUNDED = 90, UNION = 91, USING = 92, WEEK = 93, WHEN = 94, 
    WHERE = 95, WHILE = 96, WINDOW = 97, WITH = 98, YEAR = 99, ESCAPE_CHAR_COMMON = 100, 
    IDENTIFIER = 101, FLOATING_LITERAL = 102, OCTAL_LITERAL = 103, DECIMAL_LITERAL = 104, 
    HEXADECIMAL_LITERAL = 105, STRING_LITERAL = 106, ARROW = 107, ASTERISK = 108, 
    BACKQUOTE = 109, BACKSLASH = 110, COLON = 111, COMMA = 112, CONCAT = 113, 
    DASH = 114, DOLLAR = 115, DOT = 116, EQ_DOUBLE = 117, EQ_SINGLE = 118, 
    GT_EQ = 119, GT = 120, HASH = 121, IREGEX_SINGLE = 122, IREGEX_DOUBLE = 123, 
    LBRACE = 124, LBRACKET = 125, LPAREN = 126, LT_EQ = 127, LT = 128, NOT_EQ = 129, 
    NOT_IREGEX = 130, NOT_REGEX = 131, NULLISH = 132, PERCENT = 133, PLUS = 134, 
    QUERY = 135, QUOTE_DOUBLE = 136, QUOTE_SINGLE_TEMPLATE = 137, QUOTE_SINGLE_TEMPLATE_FULL = 138, 
    QUOTE_SINGLE = 139, REGEX_SINGLE = 140, REGEX_DOUBLE = 141, RBRACE = 142, 
    RBRACKET = 143, RPAREN = 144, SEMICOLON = 145, SLASH = 146, UNDERSCORE = 147, 
    MULTI_LINE_COMMENT = 148, SINGLE_LINE_COMMENT = 149, WHITESPACE = 150, 
    STRING_TEXT = 151, STRING_ESCAPE_TRIGGER = 152, FULL_STRING_TEXT = 153, 
    FULL_STRING_ESCAPE_TRIGGER = 154
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

