

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
    MATERIALIZED = 58, MINUTE = 59, MONTH = 60, NAME = 61, NAN_SQL = 62, 
    NOT = 63, NULL_SQL = 64, NULLS = 65, OFFSET = 66, ON = 67, OR = 68, 
    ORDER = 69, OUTER = 70, OVER = 71, PARTITION = 72, PRECEDING = 73, PREWHERE = 74, 
    QUARTER = 75, RANGE = 76, RECURSIVE = 77, RETURN = 78, RIGHT = 79, ROLLUP = 80, 
    ROW = 81, ROWS = 82, SAMPLE = 83, SECOND = 84, SELECT = 85, SEMI = 86, 
    SETTINGS = 87, SUBSTRING = 88, THEN = 89, THROW = 90, TIES = 91, TIMESTAMP = 92, 
    TO = 93, TOP = 94, TOTALS = 95, TRAILING = 96, TRIM = 97, TRUNCATE = 98, 
    TRY = 99, UNBOUNDED = 100, UNION = 101, USING = 102, VALUES = 103, WEEK = 104, 
    WHEN = 105, WHERE = 106, WHILE = 107, WINDOW = 108, WITH = 109, YEAR = 110, 
    ESCAPE_CHAR_COMMON = 111, IDENTIFIER = 112, FLOATING_LITERAL = 113, 
    OCTAL_LITERAL = 114, DECIMAL_LITERAL = 115, HEXADECIMAL_LITERAL = 116, 
    STRING_LITERAL = 117, ARROW = 118, ASTERISK = 119, BACKQUOTE = 120, 
    BACKSLASH = 121, DOUBLECOLON = 122, COLON = 123, COMMA = 124, CONCAT = 125, 
    DASH = 126, DOLLAR = 127, DOT = 128, EQ_DOUBLE = 129, EQ_SINGLE = 130, 
    GT_EQ = 131, GT = 132, HASH = 133, IREGEX_SINGLE = 134, IREGEX_DOUBLE = 135, 
    LBRACE = 136, LBRACKET = 137, LPAREN = 138, LT_EQ = 139, LT = 140, LT_SLASH = 141, 
    NOT_EQ = 142, NOT_IREGEX = 143, NOT_REGEX = 144, NULL_PROPERTY = 145, 
    NULLISH = 146, PERCENT = 147, PLUS = 148, QUERY = 149, QUOTE_DOUBLE = 150, 
    QUOTE_SINGLE_TEMPLATE = 151, QUOTE_SINGLE_TEMPLATE_FULL = 152, QUOTE_SINGLE = 153, 
    REGEX_SINGLE = 154, REGEX_DOUBLE = 155, RBRACE = 156, RBRACKET = 157, 
    RPAREN = 158, SEMICOLON = 159, SLASH = 160, SLASH_GT = 161, UNDERSCORE = 162, 
    MULTI_LINE_COMMENT = 163, SINGLE_LINE_COMMENT = 164, WHITESPACE = 165, 
    STRING_TEXT = 166, STRING_ESCAPE_TRIGGER = 167, FULL_STRING_TEXT = 168, 
    FULL_STRING_ESCAPE_TRIGGER = 169, TAG_WS = 170, TAGC_WS = 171, HOGQLX_TEXT_TEXT = 172, 
    HOGQLX_TEXT_WS = 173
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

