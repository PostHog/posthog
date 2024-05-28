
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
    LAST = 47, LEADING = 48, LEFT = 49, LIKE = 50, LIMIT = 51, MINUTE = 52, 
    MONTH = 53, NAN_SQL = 54, NOT = 55, NULL_SQL = 56, NULLS = 57, OFFSET = 58, 
    ON = 59, OR = 60, ORDER = 61, OUTER = 62, OVER = 63, PARTITION = 64, 
    PRECEDING = 65, PREWHERE = 66, QUARTER = 67, RANGE = 68, RETURN = 69, 
    RIGHT = 70, ROLLUP = 71, ROW = 72, ROWS = 73, SAMPLE = 74, SECOND = 75, 
    SELECT = 76, SEMI = 77, SETTINGS = 78, SUBSTRING = 79, THEN = 80, TIES = 81, 
    TIMESTAMP = 82, TO = 83, TOP = 84, TOTALS = 85, TRAILING = 86, TRIM = 87, 
    TRUNCATE = 88, UNBOUNDED = 89, UNION = 90, USING = 91, VAR = 92, WEEK = 93, 
    WHEN = 94, WHERE = 95, WHILE = 96, WINDOW = 97, WITH = 98, YEAR = 99, 
    ESCAPE_CHAR_SINGLE = 100, ESCAPE_CHAR_DOUBLE = 101, IDENTIFIER = 102, 
    FLOATING_LITERAL = 103, OCTAL_LITERAL = 104, DECIMAL_LITERAL = 105, 
    HEXADECIMAL_LITERAL = 106, STRING_LITERAL = 107, ARROW = 108, ASTERISK = 109, 
    BACKQUOTE = 110, BACKSLASH = 111, COLON = 112, COMMA = 113, CONCAT = 114, 
    DASH = 115, DOLLAR = 116, DOT = 117, EQ_DOUBLE = 118, EQ_SINGLE = 119, 
    GT_EQ = 120, GT = 121, HASH = 122, IREGEX_SINGLE = 123, IREGEX_DOUBLE = 124, 
    LBRACE = 125, LBRACKET = 126, LPAREN = 127, LT_EQ = 128, LT = 129, NOT_EQ = 130, 
    NOT_IREGEX = 131, NOT_REGEX = 132, NULLISH = 133, PERCENT = 134, PLUS = 135, 
    QUERY = 136, QUOTE_DOUBLE = 137, QUOTE_SINGLE = 138, REGEX_SINGLE = 139, 
    REGEX_DOUBLE = 140, RBRACE = 141, RBRACKET = 142, RPAREN = 143, SEMICOLON = 144, 
    SLASH = 145, UNDERSCORE = 146, MULTI_LINE_COMMENT = 147, SINGLE_LINE_COMMENT = 148, 
    WHITESPACE = 149
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

