

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
    WHEN = 105, WHERE = 106, WHILE = 107, WINDOW = 108, WITH = 109, WITHIN = 110, 
    YEAR = 111, ESCAPE_CHAR_COMMON = 112, IDENTIFIER = 113, FLOATING_LITERAL = 114, 
    OCTAL_LITERAL = 115, DECIMAL_LITERAL = 116, HEXADECIMAL_LITERAL = 117, 
    STRING_LITERAL = 118, ARROW = 119, ASTERISK = 120, BACKQUOTE = 121, 
    BACKSLASH = 122, DOUBLECOLON = 123, COLON = 124, COMMA = 125, CONCAT = 126, 
    DASH = 127, DOLLAR = 128, DOT = 129, EQ_DOUBLE = 130, EQ_SINGLE = 131, 
    GT_EQ = 132, GT = 133, HASH = 134, IREGEX_SINGLE = 135, IREGEX_DOUBLE = 136, 
    LBRACE = 137, LBRACKET = 138, LPAREN = 139, LT_EQ = 140, LT = 141, LT_SLASH = 142, 
    NOT_EQ = 143, NOT_IREGEX = 144, NOT_REGEX = 145, NULL_PROPERTY = 146, 
    NULLISH = 147, PERCENT = 148, PLUS = 149, QUERY = 150, QUOTE_DOUBLE = 151, 
    QUOTE_SINGLE_TEMPLATE = 152, QUOTE_SINGLE_TEMPLATE_FULL = 153, QUOTE_SINGLE = 154, 
    REGEX_SINGLE = 155, REGEX_DOUBLE = 156, RBRACE = 157, RBRACKET = 158, 
    RPAREN = 159, SEMICOLON = 160, SLASH = 161, SLASH_GT = 162, UNDERSCORE = 163, 
    MULTI_LINE_COMMENT = 164, SINGLE_LINE_COMMENT = 165, WHITESPACE = 166, 
    STRING_TEXT = 167, STRING_ESCAPE_TRIGGER = 168, FULL_STRING_TEXT = 169, 
    FULL_STRING_ESCAPE_TRIGGER = 170, TAG_WS = 171, TAGC_WS = 172, HOGQLX_TEXT_TEXT = 173, 
    HOGQLX_TEXT_WS = 174
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

