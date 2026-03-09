

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
    END = 27, EXCEPT = 28, EXTRACT = 29, FINAL = 30, FINALLY = 31, FIRST = 32, 
    FN = 33, FOLLOWING = 34, FOR = 35, FROM = 36, FULL = 37, FUN = 38, GROUP = 39, 
    GROUPING = 40, HAVING = 41, HOUR = 42, ID = 43, IF = 44, ILIKE = 45, 
    IN = 46, INF = 47, INNER = 48, INTERSECT = 49, INTERVAL = 50, IS = 51, 
    JOIN = 52, KEY = 53, LAMBDA = 54, LAST = 55, LEADING = 56, LEFT = 57, 
    LET = 58, LIKE = 59, LIMIT = 60, MATERIALIZED = 61, MINUTE = 62, MONTH = 63, 
    NAME = 64, NAN_SQL = 65, NOT = 66, NULL_SQL = 67, NULLS = 68, OFFSET = 69, 
    ON = 70, OR = 71, ORDER = 72, OUTER = 73, OVER = 74, PARTITION = 75, 
    PRECEDING = 76, PREWHERE = 77, QUALIFY = 78, QUARTER = 79, RANGE = 80, 
    RECURSIVE = 81, RETURN = 82, RIGHT = 83, ROLLUP = 84, ROW = 85, ROWS = 86, 
    SAMPLE = 87, SECOND = 88, SELECT = 89, SEMI = 90, SETS = 91, SETTINGS = 92, 
    SUBSTRING = 93, THEN = 94, THROW = 95, TIES = 96, TIMESTAMP = 97, TO = 98, 
    TOP = 99, TOTALS = 100, TRAILING = 101, TRIM = 102, TRUNCATE = 103, 
    TRY = 104, UNBOUNDED = 105, UNION = 106, USING = 107, WEEK = 108, WHEN = 109, 
    WHERE = 110, WHILE = 111, WINDOW = 112, WITH = 113, YEAR = 114, ESCAPE_CHAR_COMMON = 115, 
    IDENTIFIER = 116, FLOATING_LITERAL = 117, OCTAL_LITERAL = 118, DECIMAL_LITERAL = 119, 
    HEXADECIMAL_LITERAL = 120, STRING_LITERAL = 121, ARROW = 122, ASTERISK = 123, 
    BACKQUOTE = 124, BACKSLASH = 125, DOUBLECOLON = 126, COLON = 127, COMMA = 128, 
    CONCAT = 129, DASH = 130, DOLLAR = 131, DOT = 132, EQ_DOUBLE = 133, 
    EQ_SINGLE = 134, GT_EQ = 135, GT = 136, HASH = 137, IREGEX_SINGLE = 138, 
    IREGEX_DOUBLE = 139, LBRACE = 140, LBRACKET = 141, LPAREN = 142, LT_EQ = 143, 
    LT = 144, LT_SLASH = 145, NOT_EQ = 146, NOT_IREGEX = 147, NOT_REGEX = 148, 
    NULL_PROPERTY = 149, NULLISH = 150, PERCENT = 151, PLUS = 152, QUERY = 153, 
    QUOTE_DOUBLE = 154, QUOTE_SINGLE_TEMPLATE = 155, QUOTE_SINGLE_TEMPLATE_FULL = 156, 
    QUOTE_SINGLE = 157, REGEX_SINGLE = 158, REGEX_DOUBLE = 159, RBRACE = 160, 
    RBRACKET = 161, RPAREN = 162, SEMICOLON = 163, SLASH = 164, SLASH_GT = 165, 
    UNDERSCORE = 166, MULTI_LINE_COMMENT = 167, SINGLE_LINE_COMMENT = 168, 
    WHITESPACE = 169, STRING_TEXT = 170, STRING_ESCAPE_TRIGGER = 171, FULL_STRING_TEXT = 172, 
    FULL_STRING_ESCAPE_TRIGGER = 173, TAG_WS = 174, TAGC_WS = 175, HOGQLX_TEXT_TEXT = 176, 
    HOGQLX_TEXT_WS = 177
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

