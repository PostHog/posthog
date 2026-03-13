

#include <cctype>



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
    GROUPING = 39, HAVING = 40, HOUR = 41, ID = 42, IF = 43, ILIKE = 44, 
    IN = 45, INF = 46, INNER = 47, INTERSECT = 48, INTERVAL = 49, IS = 50, 
    JOIN = 51, KEY = 52, LAST = 53, LEADING = 54, LEFT = 55, LET = 56, LIKE = 57, 
    LIMIT = 58, MATERIALIZED = 59, MINUTE = 60, MONTH = 61, NAME = 62, NAN_SQL = 63, 
    NOT = 64, NULL_SQL = 65, NULLS = 66, OFFSET = 67, ON = 68, OR = 69, 
    ORDER = 70, OUTER = 71, OVER = 72, PARTITION = 73, PRECEDING = 74, PREWHERE = 75, 
    QUALIFY = 76, QUARTER = 77, RANGE = 78, RECURSIVE = 79, RETURN = 80, 
    RIGHT = 81, ROLLUP = 82, ROW = 83, ROWS = 84, SAMPLE = 85, SECOND = 86, 
    SELECT = 87, SEMI = 88, SETS = 89, SETTINGS = 90, SUBSTRING = 91, THEN = 92, 
    THROW = 93, TIES = 94, TIMESTAMP = 95, TO = 96, TOP = 97, TOTALS = 98, 
    TRAILING = 99, TRIM = 100, TRUNCATE = 101, TRY = 102, UNBOUNDED = 103, 
    UNION = 104, USING = 105, WEEK = 106, WHEN = 107, WHERE = 108, WHILE = 109, 
    WINDOW = 110, WITH = 111, YEAR = 112, ESCAPE_CHAR_COMMON = 113, IDENTIFIER = 114, 
    FLOATING_LITERAL = 115, OCTAL_LITERAL = 116, DECIMAL_LITERAL = 117, 
    HEXADECIMAL_LITERAL = 118, STRING_LITERAL = 119, ARROW = 120, ASTERISK = 121, 
    BACKQUOTE = 122, BACKSLASH = 123, DOUBLECOLON = 124, COLON = 125, COMMA = 126, 
    CONCAT = 127, DASH = 128, DOLLAR = 129, DOT = 130, EQ_DOUBLE = 131, 
    EQ_SINGLE = 132, GT_EQ = 133, GT = 134, HASH = 135, IREGEX_SINGLE = 136, 
    IREGEX_DOUBLE = 137, LBRACE = 138, LBRACKET = 139, LPAREN = 140, LT_EQ = 141, 
    LT = 142, LT_SLASH = 143, NOT_EQ = 144, NOT_IREGEX = 145, NOT_REGEX = 146, 
    NULL_PROPERTY = 147, NULLISH = 148, PERCENT = 149, PLUS = 150, QUERY = 151, 
    QUOTE_DOUBLE = 152, QUOTE_SINGLE_TEMPLATE = 153, QUOTE_SINGLE_TEMPLATE_FULL = 154, 
    QUOTE_SINGLE = 155, REGEX_SINGLE = 156, REGEX_DOUBLE = 157, RBRACE = 158, 
    RBRACKET = 159, RPAREN = 160, SEMICOLON = 161, SLASH = 162, SLASH_GT = 163, 
    UNDERSCORE = 164, MULTI_LINE_COMMENT = 165, SINGLE_LINE_COMMENT = 166, 
    WHITESPACE = 167, STRING_TEXT = 168, STRING_ESCAPE_TRIGGER = 169, FULL_STRING_TEXT = 170, 
    FULL_STRING_ESCAPE_TRIGGER = 171, TAG_WS = 172, TAGC_WS = 173, HOGQLX_TEXT_TEXT = 174, 
    HOGQLX_TEXT_WS = 175
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

