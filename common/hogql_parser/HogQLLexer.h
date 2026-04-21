

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
    END = 27, EXCEPT = 28, EXCLUDE = 29, EXTRACT = 30, FINAL = 31, FILL = 32, 
    FILTER = 33, FINALLY = 34, FIRST = 35, FN = 36, FOLLOWING = 37, FOR = 38, 
    FROM = 39, FULL = 40, FUN = 41, GROUP = 42, GROUPING = 43, HAVING = 44, 
    HOUR = 45, ID = 46, IF = 47, ILIKE = 48, IGNORE = 49, INCLUDE = 50, 
    IN = 51, INF = 52, INNER = 53, INTERSECT = 54, INTERPOLATE = 55, INTERVAL = 56, 
    IS = 57, JOIN = 58, KEY = 59, LAMBDA = 60, LAST = 61, LEADING = 62, 
    LEFT = 63, LET = 64, LIKE = 65, LIMIT = 66, MATERIALIZED = 67, MINUTE = 68, 
    MONTH = 69, NAME = 70, NATURAL = 71, NAN_SQL = 72, NOT = 73, NULL_SQL = 74, 
    NULLS = 75, OFFSET = 76, ON = 77, OR = 78, ORDER = 79, OUTER = 80, OVER = 81, 
    PARTITION = 82, PIVOT = 83, POSITIONAL = 84, PRECEDING = 85, PREWHERE = 86, 
    QUALIFY = 87, QUARTER = 88, RANGE = 89, RECURSIVE = 90, REPLACE = 91, 
    RETURN = 92, RIGHT = 93, ROLLUP = 94, ROW = 95, ROWS = 96, SAMPLE = 97, 
    SECOND = 98, SELECT = 99, SEMI = 100, SETS = 101, SETTINGS = 102, STEP = 103, 
    SUBSTRING = 104, THEN = 105, THROW = 106, TIES = 107, TIMESTAMP = 108, 
    TIME = 109, LOCAL = 110, ZONE = 111, TO = 112, TOP = 113, TOTALS = 114, 
    TRAILING = 115, TRIM = 116, TRUNCATE = 117, TRY = 118, TRY_CAST = 119, 
    UNBOUNDED = 120, UNION = 121, UNPIVOT = 122, USING = 123, VALUES = 124, 
    WEEK = 125, WHEN = 126, WHERE = 127, WHILE = 128, WINDOW = 129, WITH = 130, 
    WITHIN = 131, YEAR = 132, ESCAPE_CHAR_COMMON = 133, IDENTIFIER = 134, 
    QUOTED_IDENTIFIER = 135, FLOATING_LITERAL = 136, OCTAL_LITERAL = 137, 
    DECIMAL_LITERAL = 138, HEXADECIMAL_LITERAL = 139, STRING_LITERAL = 140, 
    ARROW = 141, ASTERISK = 142, BACKQUOTE = 143, BACKSLASH = 144, DOUBLECOLON = 145, 
    COLONEQUALS = 146, COLON = 147, COMMA = 148, CONCAT = 149, DASH = 150, 
    DOLLAR = 151, DOT = 152, EQ_DOUBLE = 153, EQ_SINGLE = 154, GT_EQ = 155, 
    GT = 156, HASH = 157, IREGEX_SINGLE = 158, IREGEX_DOUBLE = 159, LBRACE = 160, 
    LBRACKET = 161, LPAREN = 162, LT_EQ = 163, LT = 164, LT_SLASH = 165, 
    NOT_EQ = 166, NOT_IREGEX = 167, NOT_REGEX = 168, NULL_PROPERTY = 169, 
    NULLISH = 170, PERCENT = 171, PLUS = 172, QUERY = 173, QUOTE_DOUBLE = 174, 
    QUOTE_SINGLE_TEMPLATE = 175, QUOTE_SINGLE_TEMPLATE_FULL = 176, QUOTE_SINGLE = 177, 
    REGEX_SINGLE = 178, REGEX_DOUBLE = 179, RBRACE = 180, RBRACKET = 181, 
    RPAREN = 182, SEMICOLON = 183, SLASH = 184, SLASH_GT = 185, UNDERSCORE = 186, 
    MULTI_LINE_COMMENT = 187, SINGLE_LINE_COMMENT = 188, WHITESPACE = 189, 
    STRING_TEXT = 190, STRING_ESCAPE_TRIGGER = 191, FULL_STRING_TEXT = 192, 
    FULL_STRING_ESCAPE_TRIGGER = 193, TAG_WS = 194, TAGC_WS = 195, HOGQLX_TEXT_TEXT = 196, 
    HOGQLX_TEXT_WS = 197
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
              if (ch <= 0 || ch == '\n' || ch == '\r')
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

