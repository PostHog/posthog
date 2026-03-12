

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
    VALUES = 110, WEEK = 111, WHEN = 112, WHERE = 113, WHILE = 114, WINDOW = 115, 
    WITH = 116, YEAR = 117, ESCAPE_CHAR_COMMON = 118, IDENTIFIER = 119, 
    FLOATING_LITERAL = 120, OCTAL_LITERAL = 121, DECIMAL_LITERAL = 122, 
    HEXADECIMAL_LITERAL = 123, STRING_LITERAL = 124, ARROW = 125, ASTERISK = 126, 
    BACKQUOTE = 127, BACKSLASH = 128, DOUBLECOLON = 129, COLONEQUALS = 130, 
    COLON = 131, COMMA = 132, CONCAT = 133, DASH = 134, DOLLAR = 135, DOT = 136, 
    EQ_DOUBLE = 137, EQ_SINGLE = 138, GT_EQ = 139, GT = 140, HASH = 141, 
    IREGEX_SINGLE = 142, IREGEX_DOUBLE = 143, LBRACE = 144, LBRACKET = 145, 
    LPAREN = 146, LT_EQ = 147, LT = 148, LT_SLASH = 149, NOT_EQ = 150, NOT_IREGEX = 151, 
    NOT_REGEX = 152, NULL_PROPERTY = 153, NULLISH = 154, PERCENT = 155, 
    PLUS = 156, QUERY = 157, QUOTE_DOUBLE = 158, QUOTE_SINGLE_TEMPLATE = 159, 
    QUOTE_SINGLE_TEMPLATE_FULL = 160, QUOTE_SINGLE = 161, REGEX_SINGLE = 162, 
    REGEX_DOUBLE = 163, RBRACE = 164, RBRACKET = 165, RPAREN = 166, SEMICOLON = 167, 
    SLASH = 168, SLASH_GT = 169, UNDERSCORE = 170, MULTI_LINE_COMMENT = 171, 
    SINGLE_LINE_COMMENT = 172, WHITESPACE = 173, STRING_TEXT = 174, STRING_ESCAPE_TRIGGER = 175, 
    FULL_STRING_TEXT = 176, FULL_STRING_ESCAPE_TRIGGER = 177, TAG_WS = 178, 
    TAGC_WS = 179, HOGQLX_TEXT_TEXT = 180, HOGQLX_TEXT_WS = 181
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

