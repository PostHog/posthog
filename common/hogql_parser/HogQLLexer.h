
// Generated from HogQLLexer.g4 by ANTLR 4.13.2

#pragma once


#include "antlr4-runtime.h"




class  HogQLLexer : public antlr4::Lexer {
public:
  enum {
    ALL = 1, AND = 2, ANTI = 3, ANY = 4, ARRAY = 5, AS = 6, ASCENDING = 7, 
    ASOF = 8, BETWEEN = 9, BOTH = 10, BY = 11, CASE = 12, CAST = 13, CATCH = 14, 
    COHORT = 15, COLLATE = 16, CREATE = 17, CROSS = 18, CUBE = 19, CURRENT = 20, 
    DATE = 21, DAY = 22, DESC = 23, DESCENDING = 24, DISTINCT = 25, ELSE = 26, 
    END = 27, EXCEPT = 28, EXTRACT = 29, FINAL = 30, FINALLY = 31, FIRST = 32, 
    FN = 33, FOLLOWING = 34, FOR = 35, FROM = 36, FULL = 37, FUN = 38, GROUP = 39, 
    HAVING = 40, HOUR = 41, ID = 42, IF = 43, ILIKE = 44, IN = 45, INF = 46, 
    INNER = 47, INTERSECT = 48, INTERVAL = 49, IS = 50, JOIN = 51, KEY = 52, 
    LAST = 53, LEADING = 54, LEFT = 55, LET = 56, LIKE = 57, LIMIT = 58, 
    MINUTE = 59, MONTH = 60, NAN_SQL = 61, NOT = 62, NULL_SQL = 63, NULLS = 64, 
    OFFSET = 65, ON = 66, OR = 67, ORDER = 68, OUTER = 69, OVER = 70, PARTITION = 71, 
    PRECEDING = 72, PREWHERE = 73, QUARTER = 74, RANGE = 75, RETURN = 76, 
    RIGHT = 77, ROLLUP = 78, ROW = 79, ROWS = 80, SAMPLE = 81, SECOND = 82, 
    SELECT = 83, SEMI = 84, SETTINGS = 85, SUBSTRING = 86, TABLE = 87, THEN = 88, 
    THROW = 89, TIES = 90, TIMESTAMP = 91, TO = 92, TOP = 93, TOTALS = 94, 
    TRAILING = 95, TRIM = 96, TRUNCATE = 97, TRY = 98, UNBOUNDED = 99, UNION = 100, 
    USING = 101, WEEK = 102, WHEN = 103, WHERE = 104, WHILE = 105, WINDOW = 106, 
    WITH = 107, YEAR = 108, ESCAPE_CHAR_COMMON = 109, IDENTIFIER = 110, 
    FLOATING_LITERAL = 111, OCTAL_LITERAL = 112, DECIMAL_LITERAL = 113, 
    HEXADECIMAL_LITERAL = 114, STRING_LITERAL = 115, ARROW = 116, ASTERISK = 117, 
    BACKQUOTE = 118, BACKSLASH = 119, COLON = 120, COMMA = 121, CONCAT = 122, 
    DASH = 123, DOLLAR = 124, DOT = 125, EQ_DOUBLE = 126, EQ_SINGLE = 127, 
    GT_EQ = 128, GT = 129, HASH = 130, IREGEX_SINGLE = 131, IREGEX_DOUBLE = 132, 
    LBRACE = 133, LBRACKET = 134, LPAREN = 135, LT_EQ = 136, LT = 137, NOT_EQ = 138, 
    NOT_IREGEX = 139, NOT_REGEX = 140, NULL_PROPERTY = 141, NULLISH = 142, 
    PERCENT = 143, PLUS = 144, QUERY = 145, QUOTE_DOUBLE = 146, QUOTE_SINGLE_TEMPLATE = 147, 
    QUOTE_SINGLE_TEMPLATE_FULL = 148, QUOTE_SINGLE = 149, REGEX_SINGLE = 150, 
    REGEX_DOUBLE = 151, RBRACE = 152, RBRACKET = 153, RPAREN = 154, SEMICOLON = 155, 
    SLASH = 156, UNDERSCORE = 157, MULTI_LINE_COMMENT = 158, SINGLE_LINE_COMMENT = 159, 
    WHITESPACE = 160, STRING_TEXT = 161, STRING_ESCAPE_TRIGGER = 162, FULL_STRING_TEXT = 163, 
    FULL_STRING_ESCAPE_TRIGGER = 164
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

