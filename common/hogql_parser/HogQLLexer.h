

#include <cctype>



// Generated from HogQLLexer.g4 by ANTLR 4.13.2

#pragma once


#include "antlr4-runtime.h"




class  HogQLLexer : public antlr4::Lexer {
public:
  enum {
    ALL = 1, AND = 2, ANTI = 3, ANY = 4, ARRAY = 5, AS = 6, ASCENDING = 7, 
    ASOF = 8, BETWEEN = 9, BOTH = 10, BY = 11, CASE = 12, CAST = 13, CATCH = 14, 
    COHORT = 15, COLLATE = 16, COLUMNS = 17, CROSS = 18, CUBE = 19, CURRENT = 20, 
    DATE = 21, DAY = 22, DESC = 23, DESCENDING = 24, DISTINCT = 25, ELSE = 26, 
    END = 27, EXCEPT = 28, EXCLUDE = 29, EXTRACT = 30, FINAL = 31, FINALLY = 32, 
    FIRST = 33, FN = 34, FOLLOWING = 35, FOR = 36, FROM = 37, FULL = 38, 
    FUN = 39, GROUP = 40, GROUPING = 41, HAVING = 42, HOUR = 43, ID = 44, 
    IF = 45, ILIKE = 46, IN = 47, INF = 48, INNER = 49, INTERSECT = 50, 
    INTERVAL = 51, IS = 52, JOIN = 53, KEY = 54, LAMBDA = 55, LAST = 56, 
    LEADING = 57, LEFT = 58, LET = 59, LIKE = 60, LIMIT = 61, MATERIALIZED = 62, 
    MINUTE = 63, MONTH = 64, NAME = 65, NAN_SQL = 66, NOT = 67, NULL_SQL = 68, 
    NULLS = 69, OFFSET = 70, ON = 71, OR = 72, ORDER = 73, OUTER = 74, OVER = 75, 
    PARTITION = 76, PIVOT = 77, PRECEDING = 78, PREWHERE = 79, QUALIFY = 80, 
    QUARTER = 81, RANGE = 82, RECURSIVE = 83, REPLACE = 84, RETURN = 85, 
    RIGHT = 86, ROLLUP = 87, ROW = 88, ROWS = 89, SAMPLE = 90, SECOND = 91, 
    SELECT = 92, SEMI = 93, SETS = 94, SETTINGS = 95, SUBSTRING = 96, THEN = 97, 
    THROW = 98, TIES = 99, TIMESTAMP = 100, TO = 101, TOP = 102, TOTALS = 103, 
    TRAILING = 104, TRIM = 105, TRUNCATE = 106, TRY = 107, TRY_CAST = 108, 
    UNBOUNDED = 109, UNION = 110, UNPIVOT = 111, USING = 112, VALUES = 113, 
    WEEK = 114, WHEN = 115, WHERE = 116, WHILE = 117, WINDOW = 118, WITH = 119, 
    WITHIN = 120, YEAR = 121, ESCAPE_CHAR_COMMON = 122, IDENTIFIER = 123, 
    FLOATING_LITERAL = 124, OCTAL_LITERAL = 125, DECIMAL_LITERAL = 126, 
    HEXADECIMAL_LITERAL = 127, STRING_LITERAL = 128, ARROW = 129, ASTERISK = 130, 
    BACKQUOTE = 131, BACKSLASH = 132, DOUBLECOLON = 133, COLONEQUALS = 134, 
    COLON = 135, COMMA = 136, CONCAT = 137, DASH = 138, DOLLAR = 139, DOT = 140, 
    EQ_DOUBLE = 141, EQ_SINGLE = 142, GT_EQ = 143, GT = 144, HASH = 145, 
    IREGEX_SINGLE = 146, IREGEX_DOUBLE = 147, LBRACE = 148, LBRACKET = 149, 
    LPAREN = 150, LT_EQ = 151, LT = 152, LT_SLASH = 153, NOT_EQ = 154, NOT_IREGEX = 155, 
    NOT_REGEX = 156, NULL_PROPERTY = 157, NULLISH = 158, PERCENT = 159, 
    PLUS = 160, QUERY = 161, QUOTE_DOUBLE = 162, QUOTE_SINGLE_TEMPLATE = 163, 
    QUOTE_SINGLE_TEMPLATE_FULL = 164, QUOTE_SINGLE = 165, REGEX_SINGLE = 166, 
    REGEX_DOUBLE = 167, RBRACE = 168, RBRACKET = 169, RPAREN = 170, SEMICOLON = 171, 
    SLASH = 172, SLASH_GT = 173, UNDERSCORE = 174, MULTI_LINE_COMMENT = 175, 
    SINGLE_LINE_COMMENT = 176, WHITESPACE = 177, STRING_TEXT = 178, STRING_ESCAPE_TRIGGER = 179, 
    FULL_STRING_TEXT = 180, FULL_STRING_ESCAPE_TRIGGER = 181, TAG_WS = 182, 
    TAGC_WS = 183, HOGQLX_TEXT_TEXT = 184, HOGQLX_TEXT_WS = 185
  };

  enum {
    IN_TEMPLATE_STRING = 1, IN_FULL_TEMPLATE_STRING = 2, HOGQLX_TAG_OPEN = 3, 
    HOGQLX_TAG_CLOSE = 4, HOGQLX_TEXT = 5
  };

  explicit HogQLLexer(antlr4::CharStream *input);

  ~HogQLLexer() override;



  /** Skip over whitespace and end-of-line comments (`// …`, `-- …`, `# …`). */
  void skipWsAndComments(std::size_t& i) {
      for (;;) {
          int ch = _input->LA(i);
          if (std::isspace(ch)) {                       // regular whitespace
              ++i;
              continue;
          }

          /*  C++ / SQL / Bash-style single-line comments  */
          if (ch == '/' && _input->LA(i + 1) == '/') {  // //
              i += 2;
          } else if (ch == '-' && _input->LA(i + 1) == '-') { // --
              i += 2;
          } else if (ch == '#') {                       // #
              ++i;
          } else {
              break;                                    // no more ws / comments
          }
          /* consume to EOL or EOF */
          while (true) {
              ch = _input->LA(i);
              if (ch == 0 || ch == '\n' || ch == '\r')
                  break;
              ++i;
          }
      }
  }

  /* ───── opening tag test ───── */

  bool isOpeningTag() {
      /* first char after '<' */
      int la1 = _input->LA(1);
      if (!std::isalpha(la1) && la1 != '_')
          return false;

      /* skip the tag name ([a-zA-Z0-9_-]*) */
      std::size_t i = 2;
      while (true) {
          int ch = _input->LA(i);
          if (std::isalnum(ch) || ch == '_' || ch == '-')
              ++i;
          else
              break;
      }

      int ch = _input->LA(i);

      /*  Immediate delimiter → definitely a tag  */
      if (ch == '>' || ch == '/')
          return true;

      /*  If the next char is whitespace, look further  */
      if (std::isspace(ch)) {
          skipWsAndComments(++i); // step past first space
          ch = _input->LA(i);
          /* tag iff next non-ws/non-comment char is alnum/underscore */
          return std::isalnum(ch) || ch == '_' || ch == '>' || ch == '/';
      }

      /* anything else (operator chars, ')', '+', …) → not a tag */
      return false;
  }



  std::string getGrammarFileName() const override;

  const std::vector<std::string>& getRuleNames() const override;

  const std::vector<std::string>& getChannelNames() const override;

  const std::vector<std::string>& getModeNames() const override;

  const antlr4::dfa::Vocabulary& getVocabulary() const override;

  antlr4::atn::SerializedATNView getSerializedATN() const override;

  const antlr4::atn::ATN& getATN() const override;

  bool sempred(antlr4::RuleContext *_localctx, size_t ruleIndex, size_t predicateIndex) override;

  // By default the static state used to implement the lexer is lazily initialized during the first
  // call to the constructor. You can call this function if you wish to initialize the static state
  // ahead of time.
  static void initialize();

private:

  // Individual action functions triggered by action() above.

  // Individual semantic predicate functions triggered by sempred() above.
  bool TAG_LT_OPENSempred(antlr4::RuleContext *_localctx, size_t predicateIndex);

};

