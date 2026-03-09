

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
    END = 27, EXCEPT = 28, EXCLUDE = 29, EXTRACT = 30, FINAL = 31, FILTER = 32, 
    FINALLY = 33, FIRST = 34, FN = 35, FOLLOWING = 36, FOR = 37, FROM = 38, 
    FULL = 39, FUN = 40, GROUP = 41, GROUPING = 42, HAVING = 43, HOUR = 44, 
    ID = 45, IF = 46, ILIKE = 47, INCLUDE = 48, IN = 49, INF = 50, INNER = 51, 
    INTERSECT = 52, INTERVAL = 53, IS = 54, JOIN = 55, KEY = 56, LAMBDA = 57, 
    LAST = 58, LEADING = 59, LEFT = 60, LET = 61, LIKE = 62, LIMIT = 63, 
    MATERIALIZED = 64, MINUTE = 65, MONTH = 66, NAME = 67, NATURAL = 68, 
    NAN_SQL = 69, NOT = 70, NULL_SQL = 71, NULLS = 72, OFFSET = 73, ON = 74, 
    OR = 75, ORDER = 76, OUTER = 77, OVER = 78, PARTITION = 79, PIVOT = 80, 
    POSITIONAL = 81, PRECEDING = 82, PREWHERE = 83, QUALIFY = 84, QUARTER = 85, 
    RANGE = 86, RECURSIVE = 87, REPLACE = 88, RETURN = 89, RIGHT = 90, ROLLUP = 91, 
    ROW = 92, ROWS = 93, SAMPLE = 94, SECOND = 95, SELECT = 96, SEMI = 97, 
    SETS = 98, SETTINGS = 99, SUBSTRING = 100, THEN = 101, THROW = 102, 
    TIES = 103, TIMESTAMP = 104, TO = 105, TOP = 106, TOTALS = 107, TRAILING = 108, 
    TRIM = 109, TRUNCATE = 110, TRY = 111, TRY_CAST = 112, UNBOUNDED = 113, 
    UNION = 114, UNPIVOT = 115, USING = 116, VALUES = 117, WEEK = 118, WHEN = 119, 
    WHERE = 120, WHILE = 121, WINDOW = 122, WITH = 123, WITHIN = 124, YEAR = 125, 
    ESCAPE_CHAR_COMMON = 126, IDENTIFIER = 127, FLOATING_LITERAL = 128, 
    OCTAL_LITERAL = 129, DECIMAL_LITERAL = 130, HEXADECIMAL_LITERAL = 131, 
    STRING_LITERAL = 132, ARROW = 133, ASTERISK = 134, BACKQUOTE = 135, 
    BACKSLASH = 136, DOUBLECOLON = 137, COLONEQUALS = 138, COLON = 139, 
    COMMA = 140, CONCAT = 141, DASH = 142, DOLLAR = 143, DOT = 144, EQ_DOUBLE = 145, 
    EQ_SINGLE = 146, GT_EQ = 147, GT = 148, HASH = 149, IREGEX_SINGLE = 150, 
    IREGEX_DOUBLE = 151, LBRACE = 152, LBRACKET = 153, LPAREN = 154, LT_EQ = 155, 
    LT = 156, LT_SLASH = 157, NOT_EQ = 158, NOT_IREGEX = 159, NOT_REGEX = 160, 
    NULL_PROPERTY = 161, NULLISH = 162, PERCENT = 163, PLUS = 164, QUERY = 165, 
    QUOTE_DOUBLE = 166, QUOTE_SINGLE_TEMPLATE = 167, QUOTE_SINGLE_TEMPLATE_FULL = 168, 
    QUOTE_SINGLE = 169, REGEX_SINGLE = 170, REGEX_DOUBLE = 171, RBRACE = 172, 
    RBRACKET = 173, RPAREN = 174, SEMICOLON = 175, SLASH = 176, SLASH_GT = 177, 
    UNDERSCORE = 178, MULTI_LINE_COMMENT = 179, SINGLE_LINE_COMMENT = 180, 
    WHITESPACE = 181, STRING_TEXT = 182, STRING_ESCAPE_TRIGGER = 183, FULL_STRING_TEXT = 184, 
    FULL_STRING_ESCAPE_TRIGGER = 185, TAG_WS = 186, TAGC_WS = 187, HOGQLX_TEXT_TEXT = 188, 
    HOGQLX_TEXT_WS = 189
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

