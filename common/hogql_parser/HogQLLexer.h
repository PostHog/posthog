

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
    ID = 45, IF = 46, ILIKE = 47, IGNORE = 48, INCLUDE = 49, IN = 50, INF = 51, 
    INNER = 52, INTERSECT = 53, INTERVAL = 54, IS = 55, JOIN = 56, KEY = 57, 
    LAMBDA = 58, LAST = 59, LEADING = 60, LEFT = 61, LET = 62, LIKE = 63, 
    LIMIT = 64, MATERIALIZED = 65, MINUTE = 66, MONTH = 67, NAME = 68, NATURAL = 69, 
    NAN_SQL = 70, NOT = 71, NULL_SQL = 72, NULLS = 73, OFFSET = 74, ON = 75, 
    OR = 76, ORDER = 77, OUTER = 78, OVER = 79, PARTITION = 80, PIVOT = 81, 
    POSITIONAL = 82, PRECEDING = 83, PREWHERE = 84, QUALIFY = 85, QUARTER = 86, 
    RANGE = 87, RECURSIVE = 88, REPLACE = 89, RETURN = 90, RIGHT = 91, ROLLUP = 92, 
    ROW = 93, ROWS = 94, SAMPLE = 95, SECOND = 96, SELECT = 97, SEMI = 98, 
    SETS = 99, SETTINGS = 100, SUBSTRING = 101, THEN = 102, THROW = 103, 
    TIES = 104, TIMESTAMP = 105, TO = 106, TOP = 107, TOTALS = 108, TRAILING = 109, 
    TRIM = 110, TRUNCATE = 111, TRY = 112, TRY_CAST = 113, UNBOUNDED = 114, 
    UNION = 115, UNPIVOT = 116, USING = 117, VALUES = 118, WEEK = 119, WHEN = 120, 
    WHERE = 121, WHILE = 122, WINDOW = 123, WITH = 124, WITHIN = 125, YEAR = 126, 
    ESCAPE_CHAR_COMMON = 127, IDENTIFIER = 128, FLOATING_LITERAL = 129, 
    OCTAL_LITERAL = 130, DECIMAL_LITERAL = 131, HEXADECIMAL_LITERAL = 132, 
    STRING_LITERAL = 133, ARROW = 134, ASTERISK = 135, BACKQUOTE = 136, 
    BACKSLASH = 137, DOUBLECOLON = 138, COLONEQUALS = 139, COLON = 140, 
    COMMA = 141, CONCAT = 142, DASH = 143, DOLLAR = 144, DOT = 145, EQ_DOUBLE = 146, 
    EQ_SINGLE = 147, GT_EQ = 148, GT = 149, HASH = 150, IREGEX_SINGLE = 151, 
    IREGEX_DOUBLE = 152, LBRACE = 153, LBRACKET = 154, LPAREN = 155, LT_EQ = 156, 
    LT = 157, LT_SLASH = 158, NOT_EQ = 159, NOT_IREGEX = 160, NOT_REGEX = 161, 
    NULL_PROPERTY = 162, NULLISH = 163, PERCENT = 164, PLUS = 165, QUERY = 166, 
    QUOTE_DOUBLE = 167, QUOTE_SINGLE_TEMPLATE = 168, QUOTE_SINGLE_TEMPLATE_FULL = 169, 
    QUOTE_SINGLE = 170, REGEX_SINGLE = 171, REGEX_DOUBLE = 172, RBRACE = 173, 
    RBRACKET = 174, RPAREN = 175, SEMICOLON = 176, SLASH = 177, SLASH_GT = 178, 
    UNDERSCORE = 179, MULTI_LINE_COMMENT = 180, SINGLE_LINE_COMMENT = 181, 
    WHITESPACE = 182, STRING_TEXT = 183, STRING_ESCAPE_TRIGGER = 184, FULL_STRING_TEXT = 185, 
    FULL_STRING_ESCAPE_TRIGGER = 186, TAG_WS = 187, TAGC_WS = 188, HOGQLX_TEXT_TEXT = 189, 
    HOGQLX_TEXT_WS = 190
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

