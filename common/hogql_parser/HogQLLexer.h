

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
    PARTITION = 76, PRECEDING = 77, PREWHERE = 78, QUALIFY = 79, QUARTER = 80, 
    RANGE = 81, RECURSIVE = 82, REPLACE = 83, RETURN = 84, RIGHT = 85, ROLLUP = 86, 
    ROW = 87, ROWS = 88, SAMPLE = 89, SECOND = 90, SELECT = 91, SEMI = 92, 
    SETS = 93, SETTINGS = 94, SUBSTRING = 95, THEN = 96, THROW = 97, TIES = 98, 
    TIMESTAMP = 99, TO = 100, TOP = 101, TOTALS = 102, TRAILING = 103, TRIM = 104, 
    TRUNCATE = 105, TRY = 106, TRY_CAST = 107, UNBOUNDED = 108, UNION = 109, 
    UNPIVOT = 110, USING = 111, VALUES = 112, WEEK = 113, WHEN = 114, WHERE = 115, 
    WHILE = 116, WINDOW = 117, WITH = 118, WITHIN = 119, YEAR = 120, ESCAPE_CHAR_COMMON = 121, 
    IDENTIFIER = 122, FLOATING_LITERAL = 123, OCTAL_LITERAL = 124, DECIMAL_LITERAL = 125, 
    HEXADECIMAL_LITERAL = 126, STRING_LITERAL = 127, ARROW = 128, ASTERISK = 129, 
    BACKQUOTE = 130, BACKSLASH = 131, DOUBLECOLON = 132, COLONEQUALS = 133, 
    COLON = 134, COMMA = 135, CONCAT = 136, DASH = 137, DOLLAR = 138, DOT = 139, 
    EQ_DOUBLE = 140, EQ_SINGLE = 141, GT_EQ = 142, GT = 143, HASH = 144, 
    IREGEX_SINGLE = 145, IREGEX_DOUBLE = 146, LBRACE = 147, LBRACKET = 148, 
    LPAREN = 149, LT_EQ = 150, LT = 151, LT_SLASH = 152, NOT_EQ = 153, NOT_IREGEX = 154, 
    NOT_REGEX = 155, NULL_PROPERTY = 156, NULLISH = 157, PERCENT = 158, 
    PLUS = 159, QUERY = 160, QUOTE_DOUBLE = 161, QUOTE_SINGLE_TEMPLATE = 162, 
    QUOTE_SINGLE_TEMPLATE_FULL = 163, QUOTE_SINGLE = 164, REGEX_SINGLE = 165, 
    REGEX_DOUBLE = 166, RBRACE = 167, RBRACKET = 168, RPAREN = 169, SEMICOLON = 170, 
    SLASH = 171, SLASH_GT = 172, UNDERSCORE = 173, MULTI_LINE_COMMENT = 174, 
    SINGLE_LINE_COMMENT = 175, WHITESPACE = 176, STRING_TEXT = 177, STRING_ESCAPE_TRIGGER = 178, 
    FULL_STRING_TEXT = 179, FULL_STRING_ESCAPE_TRIGGER = 180, TAG_WS = 181, 
    TAGC_WS = 182, HOGQLX_TEXT_TEXT = 183, HOGQLX_TEXT_WS = 184
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

