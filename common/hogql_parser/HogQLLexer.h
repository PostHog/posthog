

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
    RANGE = 81, RECURSIVE = 82, RETURN = 83, RIGHT = 84, ROLLUP = 85, ROW = 86, 
    ROWS = 87, SAMPLE = 88, SECOND = 89, SELECT = 90, SEMI = 91, SETS = 92, 
    SETTINGS = 93, SUBSTRING = 94, THEN = 95, THROW = 96, TIES = 97, TIMESTAMP = 98, 
    TO = 99, TOP = 100, TOTALS = 101, TRAILING = 102, TRIM = 103, TRUNCATE = 104, 
    TRY = 105, TRY_CAST = 106, UNBOUNDED = 107, UNION = 108, USING = 109, 
    WEEK = 110, WHEN = 111, WHERE = 112, WHILE = 113, WINDOW = 114, WITH = 115, 
    YEAR = 116, ESCAPE_CHAR_COMMON = 117, IDENTIFIER = 118, FLOATING_LITERAL = 119, 
    OCTAL_LITERAL = 120, DECIMAL_LITERAL = 121, HEXADECIMAL_LITERAL = 122, 
    STRING_LITERAL = 123, ARROW = 124, ASTERISK = 125, BACKQUOTE = 126, 
    BACKSLASH = 127, DOUBLECOLON = 128, COLONEQUALS = 129, COLON = 130, 
    COMMA = 131, CONCAT = 132, DASH = 133, DOLLAR = 134, DOT = 135, EQ_DOUBLE = 136, 
    EQ_SINGLE = 137, GT_EQ = 138, GT = 139, HASH = 140, IREGEX_SINGLE = 141, 
    IREGEX_DOUBLE = 142, LBRACE = 143, LBRACKET = 144, LPAREN = 145, LT_EQ = 146, 
    LT = 147, LT_SLASH = 148, NOT_EQ = 149, NOT_IREGEX = 150, NOT_REGEX = 151, 
    NULL_PROPERTY = 152, NULLISH = 153, PERCENT = 154, PLUS = 155, QUERY = 156, 
    QUOTE_DOUBLE = 157, QUOTE_SINGLE_TEMPLATE = 158, QUOTE_SINGLE_TEMPLATE_FULL = 159, 
    QUOTE_SINGLE = 160, REGEX_SINGLE = 161, REGEX_DOUBLE = 162, RBRACE = 163, 
    RBRACKET = 164, RPAREN = 165, SEMICOLON = 166, SLASH = 167, SLASH_GT = 168, 
    UNDERSCORE = 169, MULTI_LINE_COMMENT = 170, SINGLE_LINE_COMMENT = 171, 
    WHITESPACE = 172, STRING_TEXT = 173, STRING_ESCAPE_TRIGGER = 174, FULL_STRING_TEXT = 175, 
    FULL_STRING_ESCAPE_TRIGGER = 176, TAG_WS = 177, TAGC_WS = 178, HOGQLX_TEXT_TEXT = 179, 
    HOGQLX_TEXT_WS = 180
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

