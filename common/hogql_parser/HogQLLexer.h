

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
    MINUTE = 58, MONTH = 59, NAN_SQL = 60, NOT = 61, NULL_SQL = 62, NULLS = 63, 
    OFFSET = 64, ON = 65, OR = 66, ORDER = 67, OUTER = 68, OVER = 69, PARTITION = 70, 
    PRECEDING = 71, PREWHERE = 72, QUARTER = 73, RANGE = 74, RECURSIVE = 75, 
    RETURN = 76, RIGHT = 77, ROLLUP = 78, ROW = 79, ROWS = 80, SAMPLE = 81, 
    SECOND = 82, SELECT = 83, SEMI = 84, SETTINGS = 85, SUBSTRING = 86, 
    THEN = 87, THROW = 88, TIES = 89, TIMESTAMP = 90, TO = 91, TOP = 92, 
    TOTALS = 93, TRAILING = 94, TRIM = 95, TRUNCATE = 96, TRY = 97, UNBOUNDED = 98, 
    UNION = 99, USING = 100, WEEK = 101, WHEN = 102, WHERE = 103, WHILE = 104, 
    WINDOW = 105, WITH = 106, YEAR = 107, ESCAPE_CHAR_COMMON = 108, IDENTIFIER = 109, 
    FLOATING_LITERAL = 110, OCTAL_LITERAL = 111, DECIMAL_LITERAL = 112, 
    HEXADECIMAL_LITERAL = 113, STRING_LITERAL = 114, ARROW = 115, ASTERISK = 116, 
    BACKQUOTE = 117, BACKSLASH = 118, DOUBLECOLON = 119, COLON = 120, COMMA = 121, 
    CONCAT = 122, DASH = 123, DOLLAR = 124, DOT = 125, EQ_DOUBLE = 126, 
    EQ_SINGLE = 127, GT_EQ = 128, GT = 129, HASH = 130, IREGEX_SINGLE = 131, 
    IREGEX_DOUBLE = 132, LBRACE = 133, LBRACKET = 134, LPAREN = 135, LT_EQ = 136, 
    LT = 137, LT_SLASH = 138, NOT_EQ = 139, NOT_IREGEX = 140, NOT_REGEX = 141, 
    NULL_PROPERTY = 142, NULLISH = 143, PERCENT = 144, PLUS = 145, QUERY = 146, 
    QUOTE_DOUBLE = 147, QUOTE_SINGLE_TEMPLATE = 148, QUOTE_SINGLE_TEMPLATE_FULL = 149, 
    QUOTE_SINGLE = 150, REGEX_SINGLE = 151, REGEX_DOUBLE = 152, RBRACE = 153, 
    RBRACKET = 154, RPAREN = 155, SEMICOLON = 156, SLASH = 157, SLASH_GT = 158, 
    UNDERSCORE = 159, MULTI_LINE_COMMENT = 160, SINGLE_LINE_COMMENT = 161, 
    WHITESPACE = 162, STRING_TEXT = 163, STRING_ESCAPE_TRIGGER = 164, FULL_STRING_TEXT = 165, 
    FULL_STRING_ESCAPE_TRIGGER = 166, TAG_WS = 167, TAGC_WS = 168, HOGQLX_TEXT_TEXT = 169, 
    HOGQLX_TEXT_WS = 170
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

