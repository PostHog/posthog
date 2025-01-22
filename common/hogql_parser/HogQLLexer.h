
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
    EXCEPT = 27, EXTRACT = 28, FINAL = 29, FINALLY = 30, FIRST = 31, FN = 32, 
    FOLLOWING = 33, FOR = 34, FROM = 35, FULL = 36, FUN = 37, GROUP = 38, 
    HAVING = 39, HOUR = 40, ID = 41, IF = 42, ILIKE = 43, IN = 44, INF = 45, 
    INNER = 46, INTERSECT = 47, INTERVAL = 48, IS = 49, JOIN = 50, KEY = 51, 
    LAST = 52, LEADING = 53, LEFT = 54, LET = 55, LIKE = 56, LIMIT = 57, 
    MINUTE = 58, MONTH = 59, NAN_SQL = 60, NOT = 61, NULL_SQL = 62, NULLS = 63, 
    OFFSET = 64, ON = 65, OR = 66, ORDER = 67, OUTER = 68, OVER = 69, PARTITION = 70, 
    PRECEDING = 71, PREWHERE = 72, QUARTER = 73, RANGE = 74, RETURN = 75, 
    RIGHT = 76, ROLLUP = 77, ROW = 78, ROWS = 79, SAMPLE = 80, SECOND = 81, 
    SELECT = 82, SEMI = 83, SETTINGS = 84, SUBSTRING = 85, THEN = 86, THROW = 87, 
    TIES = 88, TIMESTAMP = 89, TO = 90, TOP = 91, TOTALS = 92, TRAILING = 93, 
    TRIM = 94, TRUNCATE = 95, TRY = 96, UNBOUNDED = 97, UNION = 98, USING = 99, 
    WEEK = 100, WHEN = 101, WHERE = 102, WHILE = 103, WINDOW = 104, WITH = 105, 
    YEAR = 106, ESCAPE_CHAR_COMMON = 107, IDENTIFIER = 108, FLOATING_LITERAL = 109, 
    OCTAL_LITERAL = 110, DECIMAL_LITERAL = 111, HEXADECIMAL_LITERAL = 112, 
    STRING_LITERAL = 113, ARROW = 114, ASTERISK = 115, BACKQUOTE = 116, 
    BACKSLASH = 117, COLON = 118, COMMA = 119, CONCAT = 120, DASH = 121, 
    DOLLAR = 122, DOT = 123, EQ_DOUBLE = 124, EQ_SINGLE = 125, GT_EQ = 126, 
    GT = 127, HASH = 128, IREGEX_SINGLE = 129, IREGEX_DOUBLE = 130, LBRACE = 131, 
    LBRACKET = 132, LPAREN = 133, LT_EQ = 134, LT = 135, NOT_EQ = 136, NOT_IREGEX = 137, 
    NOT_REGEX = 138, NULL_PROPERTY = 139, NULLISH = 140, PERCENT = 141, 
    PLUS = 142, QUERY = 143, QUOTE_DOUBLE = 144, QUOTE_SINGLE_TEMPLATE = 145, 
    QUOTE_SINGLE_TEMPLATE_FULL = 146, QUOTE_SINGLE = 147, REGEX_SINGLE = 148, 
    REGEX_DOUBLE = 149, RBRACE = 150, RBRACKET = 151, RPAREN = 152, SEMICOLON = 153, 
    SLASH = 154, UNDERSCORE = 155, MULTI_LINE_COMMENT = 156, SINGLE_LINE_COMMENT = 157, 
    WHITESPACE = 158, STRING_TEXT = 159, STRING_ESCAPE_TRIGGER = 160, FULL_STRING_TEXT = 161, 
    FULL_STRING_ESCAPE_TRIGGER = 162
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

