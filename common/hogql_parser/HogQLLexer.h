

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
    QUOTED_IDENTIFIER = 135, FLOATING_LITERAL = 136, BINARY_LITERAL = 137, 
    OCTAL_LITERAL = 138, DECIMAL_LITERAL = 139, HEXADECIMAL_LITERAL = 140, 
    OCTAL_PREFIX_LITERAL = 141, MALFORMED_BINARY_LITERAL = 142, STRING_LITERAL = 143, 
    ARROW = 144, ASTERISK = 145, BACKQUOTE = 146, BACKSLASH = 147, DOUBLECOLON = 148, 
    COLONEQUALS = 149, COLON = 150, COMMA = 151, CONCAT = 152, DASH = 153, 
    DOLLAR = 154, DOT = 155, EQ_DOUBLE = 156, EQ_SINGLE = 157, GT_EQ = 158, 
    GT = 159, HASH = 160, IREGEX_SINGLE = 161, IREGEX_DOUBLE = 162, LBRACE = 163, 
    LBRACKET = 164, LPAREN = 165, NULL_SAFE_EQ = 166, LT_EQ = 167, LT = 168, 
    LT_SLASH = 169, NOT_EQ = 170, NOT_IREGEX = 171, NOT_REGEX = 172, NULL_PROPERTY = 173, 
    NULLISH = 174, PERCENT = 175, PLUS = 176, QUERY = 177, QUOTE_DOUBLE = 178, 
    QUOTE_SINGLE_TEMPLATE = 179, QUOTE_SINGLE_TEMPLATE_FULL = 180, QUOTE_SINGLE = 181, 
    REGEX_SINGLE = 182, REGEX_DOUBLE = 183, RBRACE = 184, RBRACKET = 185, 
    RPAREN = 186, SEMICOLON = 187, SLASH = 188, SLASH_GT = 189, UNDERSCORE = 190, 
    MULTI_LINE_COMMENT = 191, SINGLE_LINE_COMMENT = 192, HASH_COMMENT = 193, 
    WHITESPACE = 194, UNEXPECTED_CHARACTER = 195, STRING_TEXT = 196, STRING_ESCAPE_TRIGGER = 197, 
    FULL_STRING_TEXT = 198, FULL_STRING_ESCAPE_TRIGGER = 199, TAG_MULTI_LINE_COMMENT = 200, 
    TAG_SINGLE_LINE_COMMENT = 201, TAG_WS = 202, TAGC_MULTI_LINE_COMMENT = 203, 
    TAGC_SINGLE_LINE_COMMENT = 204, TAGC_WS = 205, HOGQLX_TEXT_TEXT = 206, 
    HOGQLX_TEXT_WS = 207
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
      /* Decide whether a '<' opens a HogQLX tag or is the '<' comparison
         operator. This is a pure lexer heuristic, so when the two are
         genuinely ambiguous we bias toward the comparison operator — a
         comparison in a saved query must never silently re-tokenise into a
         broken tag. See the parser tests for the shapes this guards. */

      /* first char after '<' must start an identifier */
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

      /*  '<name>' — opening tag closed immediately (e.g. `<div>`).  */
      if (ch == '>')
          return true;

      /*  '<name/>' — self-closing tag. Require the '>' so a bare '/'
          (division, e.g. `a<b/c`) is not mistaken for a tag.  */
      if (ch == '/')
          return _input->LA(i + 1) == '>';

      /*  Anything other than whitespace here (operator chars, ')', '+',
          digits, EOF, …) is the comparison operator, not a tag.  */
      if (!std::isspace(ch))
          return false;

      /*  Whitespace after the name: look past ws/comments to the next
          meaningful char to decide.  */
      skipWsAndComments(++i); // step past first space
      ch = _input->LA(i);

      /*  '<name />' — self-closing with space before '/>'.  */
      if (ch == '/')
          return _input->LA(i + 1) == '>';

      /*  '<name attr…' — only a tag if the following identifier is a real
          attribute, i.e. it is followed by '='. A bare identifier after the
          name (e.g. the `and` in `a<b and c`) is a comparison continuation,
          not a tag attribute.  */
      if (std::isalpha(ch) || ch == '_') {
          ++i;
          while (true) {
              int c2 = _input->LA(i);
              if (std::isalnum(c2) || c2 == '_' || c2 == '-')
                  ++i;
              else
                  break;
          }
          skipWsAndComments(i);
          return _input->LA(i) == '=';
      }

      /*  '<name >' (space then '>') and everything else → comparison. An
          empty tag written with a trailing space still parses in the
          default lexer mode; biasing here keeps `x <col > y` a comparison.  */
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

