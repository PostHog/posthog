

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
    HAVING = 39, HOUR = 40, ID = 41, IF = 42, ILIKE = 43, IN = 44, INF = 45, 
    INNER = 46, INTERSECT = 47, INTERVAL = 48, IS = 49, JOIN = 50, KEY = 51, 
    LAST = 52, LEADING = 53, LEFT = 54, LET = 55, LIKE = 56, LIMIT = 57, 
    MATERIALIZED = 58, MINUTE = 59, MONTH = 60, NAN_SQL = 61, NOT = 62, 
    NULL_SQL = 63, NULLS = 64, OFFSET = 65, ON = 66, OR = 67, ORDER = 68, 
    OUTER = 69, OVER = 70, PARTITION = 71, PRECEDING = 72, PREWHERE = 73, 
    QUARTER = 74, RANGE = 75, RECURSIVE = 76, RETURN = 77, RIGHT = 78, ROLLUP = 79, 
    ROW = 80, ROWS = 81, SAMPLE = 82, SECOND = 83, SELECT = 84, SEMI = 85, 
    SETTINGS = 86, SUBSTRING = 87, THEN = 88, THROW = 89, TIES = 90, TIMESTAMP = 91, 
    TO = 92, TOP = 93, TOTALS = 94, TRAILING = 95, TRIM = 96, TRUNCATE = 97, 
    TRY = 98, UNBOUNDED = 99, UNION = 100, USING = 101, WEEK = 102, WHEN = 103, 
    WHERE = 104, WHILE = 105, WINDOW = 106, WITH = 107, YEAR = 108, ESCAPE_CHAR_COMMON = 109, 
    IDENTIFIER = 110, FLOATING_LITERAL = 111, OCTAL_LITERAL = 112, DECIMAL_LITERAL = 113, 
    HEXADECIMAL_LITERAL = 114, STRING_LITERAL = 115, ARROW = 116, ASTERISK = 117, 
    BACKQUOTE = 118, BACKSLASH = 119, DOUBLECOLON = 120, COLON = 121, COMMA = 122, 
    CONCAT = 123, DASH = 124, DOLLAR = 125, DOT = 126, EQ_DOUBLE = 127, 
    EQ_SINGLE = 128, GT_EQ = 129, GT = 130, HASH = 131, IREGEX_SINGLE = 132, 
    IREGEX_DOUBLE = 133, LBRACE = 134, LBRACKET = 135, LPAREN = 136, LT_EQ = 137, 
    LT = 138, LT_SLASH = 139, NOT_EQ = 140, NOT_IREGEX = 141, NOT_REGEX = 142, 
    NULL_PROPERTY = 143, NULLISH = 144, PERCENT = 145, PLUS = 146, QUERY = 147, 
    QUOTE_DOUBLE = 148, QUOTE_SINGLE_TEMPLATE = 149, QUOTE_SINGLE_TEMPLATE_FULL = 150, 
    QUOTE_SINGLE = 151, REGEX_SINGLE = 152, REGEX_DOUBLE = 153, RBRACE = 154, 
    RBRACKET = 155, RPAREN = 156, SEMICOLON = 157, SLASH = 158, SLASH_GT = 159, 
    UNDERSCORE = 160, MULTI_LINE_COMMENT = 161, SINGLE_LINE_COMMENT = 162, 
    WHITESPACE = 163, STRING_TEXT = 164, STRING_ESCAPE_TRIGGER = 165, FULL_STRING_TEXT = 166, 
    FULL_STRING_ESCAPE_TRIGGER = 167, TAG_WS = 168, TAGC_WS = 169, HOGQLX_TEXT_TEXT = 170, 
    HOGQLX_TEXT_WS = 171
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

