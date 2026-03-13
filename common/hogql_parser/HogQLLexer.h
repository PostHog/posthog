

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
    JOIN = 52, KEY = 53, LAST = 54, LEADING = 55, LEFT = 56, LET = 57, LIKE = 58, 
    LIMIT = 59, MATERIALIZED = 60, MINUTE = 61, MONTH = 62, NAME = 63, NAN_SQL = 64, 
    NOT = 65, NULL_SQL = 66, NULLS = 67, OFFSET = 68, ON = 69, OR = 70, 
    ORDER = 71, OUTER = 72, OVER = 73, PARTITION = 74, PRECEDING = 75, PREWHERE = 76, 
    QUALIFY = 77, QUARTER = 78, RANGE = 79, RECURSIVE = 80, RETURN = 81, 
    RIGHT = 82, ROLLUP = 83, ROW = 84, ROWS = 85, SAMPLE = 86, SECOND = 87, 
    SELECT = 88, SEMI = 89, SETS = 90, SETTINGS = 91, SUBSTRING = 92, THEN = 93, 
    THROW = 94, TIES = 95, TIMESTAMP = 96, TO = 97, TOP = 98, TOTALS = 99, 
    TRAILING = 100, TRIM = 101, TRUNCATE = 102, TRY = 103, UNBOUNDED = 104, 
    UNION = 105, USING = 106, WEEK = 107, WHEN = 108, WHERE = 109, WHILE = 110, 
    WINDOW = 111, WITH = 112, YEAR = 113, ESCAPE_CHAR_COMMON = 114, IDENTIFIER = 115, 
    FLOATING_LITERAL = 116, OCTAL_LITERAL = 117, DECIMAL_LITERAL = 118, 
    HEXADECIMAL_LITERAL = 119, STRING_LITERAL = 120, ARROW = 121, ASTERISK = 122, 
    BACKQUOTE = 123, BACKSLASH = 124, DOUBLECOLON = 125, COLON = 126, COMMA = 127, 
    CONCAT = 128, DASH = 129, DOLLAR = 130, DOT = 131, EQ_DOUBLE = 132, 
    EQ_SINGLE = 133, GT_EQ = 134, GT = 135, HASH = 136, IREGEX_SINGLE = 137, 
    IREGEX_DOUBLE = 138, LBRACE = 139, LBRACKET = 140, LPAREN = 141, LT_EQ = 142, 
    LT = 143, LT_SLASH = 144, NOT_EQ = 145, NOT_IREGEX = 146, NOT_REGEX = 147, 
    NULL_PROPERTY = 148, NULLISH = 149, PERCENT = 150, PLUS = 151, QUERY = 152, 
    QUOTE_DOUBLE = 153, QUOTE_SINGLE_TEMPLATE = 154, QUOTE_SINGLE_TEMPLATE_FULL = 155, 
    QUOTE_SINGLE = 156, REGEX_SINGLE = 157, REGEX_DOUBLE = 158, RBRACE = 159, 
    RBRACKET = 160, RPAREN = 161, SEMICOLON = 162, SLASH = 163, SLASH_GT = 164, 
    UNDERSCORE = 165, MULTI_LINE_COMMENT = 166, SINGLE_LINE_COMMENT = 167, 
    WHITESPACE = 168, STRING_TEXT = 169, STRING_ESCAPE_TRIGGER = 170, FULL_STRING_TEXT = 171, 
    FULL_STRING_ESCAPE_TRIGGER = 172, TAG_WS = 173, TAGC_WS = 174, HOGQLX_TEXT_TEXT = 175, 
    HOGQLX_TEXT_WS = 176
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

