lexer grammar HogQLLexer;

// NB! We cat either HogQLLexter.cpp.g4 or HogQLLexter.python.g4 when generating the grammar.

// NOTE: don't forget to add new keywords to the parser rule "keyword"!

// Keywords

ALL: A L L;
AND: A N D;
ANTI: A N T I;
ANY: A N Y;
ARRAY: A R R A Y;
AS: A S;
ASCENDING: A S C | A S C E N D I N G;
ASOF: A S O F;
BETWEEN: B E T W E E N;
BOTH: B O T H;
BY: B Y;
CASE: C A S E;
CAST: C A S T;
CATCH: C A T C H;
COHORT: C O H O R T;
COLLATE: C O L L A T E;
CROSS: C R O S S;
CUBE: C U B E;
CURRENT: C U R R E N T;
DATE: D A T E;
DAY: D A Y;
DESC: D E S C;
DESCENDING: D E S C E N D I N G;
DISTINCT: D I S T I N C T;
ELSE: E L S E;
END: E N D;
EXCEPT: E X C E P T;
EXTRACT: E X T R A C T;
FINAL: F I N A L;
FINALLY: F I N A L L Y;
FIRST: F I R S T;
FN: F N;
FOLLOWING: F O L L O W I N G;
FOR: F O R;
FROM: F R O M;
FULL: F U L L;
FUN: F U N;
GROUP: G R O U P;
HAVING: H A V I N G;
HOUR: H O U R;
ID: I D;
IF: I F;
ILIKE: I L I K E;
IN: I N;
INF: I N F | I N F I N I T Y;
INNER: I N N E R;
INTERSECT: I N T E R S E C T;
INTERVAL: I N T E R V A L;
IS: I S;
JOIN: J O I N;
KEY: K E Y;
LAST: L A S T;
LEADING: L E A D I N G;
LEFT: L E F T;
LET: L E T;
LIKE: L I K E;
LIMIT: L I M I T;
MINUTE: M I N U T E;
MONTH: M O N T H;
NAN_SQL: N A N; // conflicts with macro NAN
NOT: N O T;
NULL_SQL: N U L L; // conflicts with macro NULL
NULLS: N U L L S;
OFFSET: O F F S E T;
ON: O N;
OR: O R;
ORDER: O R D E R;
OUTER: O U T E R;
OVER: O V E R;
PARTITION: P A R T I T I O N;
PRECEDING: P R E C E D I N G;
PREWHERE: P R E W H E R E;
QUARTER: Q U A R T E R;
RANGE: R A N G E;
RETURN: R E T U R N;
RIGHT: R I G H T;
ROLLUP: R O L L U P;
ROW: R O W;
ROWS: R O W S;
SAMPLE: S A M P L E;
SECOND: S E C O N D;
SELECT: S E L E C T;
SEMI: S E M I;
SETTINGS: S E T T I N G S;
SUBSTRING: S U B S T R I N G;
THEN: T H E N;
THROW: T H R O W;
TIES: T I E S;
TIMESTAMP: T I M E S T A M P;
TO: T O;
TOP: T O P;
TOTALS: T O T A L S;
TRAILING: T R A I L I N G;
TRIM: T R I M;
TRUNCATE: T R U N C A T E;
TRY: T R Y;
UNBOUNDED: U N B O U N D E D;
UNION: U N I O N;
USING: U S I N G;
WEEK: W E E K;
WHEN: W H E N;
WHERE: W H E R E;
WHILE: W H I L E;
WINDOW: W I N D O W;
WITH: W I T H;
YEAR: Y E A R | Y Y Y Y;

// Tokens

// copied from clickhouse_driver/util/escape.py
ESCAPE_CHAR_COMMON
    : BACKSLASH B
    | BACKSLASH F
    | BACKSLASH R
    | BACKSLASH N
    | BACKSLASH T
    | BACKSLASH '0'
    | BACKSLASH A
    | BACKSLASH V
    | BACKSLASH BACKSLASH;

IDENTIFIER
    : (LETTER | UNDERSCORE | DOLLAR) (LETTER | UNDERSCORE | DEC_DIGIT | DOLLAR)*
    | BACKQUOTE ( ~([\\`]) | ESCAPE_CHAR_COMMON | BACKSLASH QUOTE_SINGLE | (BACKQUOTE BACKQUOTE) )* BACKQUOTE
    | QUOTE_DOUBLE ( ~([\\"]) | ESCAPE_CHAR_COMMON | BACKSLASH QUOTE_DOUBLE | (QUOTE_DOUBLE QUOTE_DOUBLE) )* QUOTE_DOUBLE
    ;
FLOATING_LITERAL
    : HEXADECIMAL_LITERAL DOT HEX_DIGIT* (P | E) (PLUS | DASH)? DEC_DIGIT+
    | HEXADECIMAL_LITERAL (P | E) (PLUS | DASH)? DEC_DIGIT+
    | DECIMAL_LITERAL DOT DEC_DIGIT* E (PLUS | DASH)? DEC_DIGIT+
    | DOT DECIMAL_LITERAL E (PLUS | DASH)? DEC_DIGIT+
    | DECIMAL_LITERAL E (PLUS | DASH)? DEC_DIGIT+
    ;
OCTAL_LITERAL: '0' OCT_DIGIT+;
DECIMAL_LITERAL: DEC_DIGIT+;
HEXADECIMAL_LITERAL: '0' X HEX_DIGIT+;

// It's important that quote-symbol is a single character.
STRING_LITERAL: QUOTE_SINGLE ( ~([\\']) | ESCAPE_CHAR_COMMON | BACKSLASH QUOTE_SINGLE | (QUOTE_SINGLE QUOTE_SINGLE) )* QUOTE_SINGLE;


// Alphabet and allowed symbols

fragment A: [aA];
fragment B: [bB];
fragment C: [cC];
fragment D: [dD];
fragment E: [eE];
fragment F: [fF];
fragment G: [gG];
fragment H: [hH];
fragment I: [iI];
fragment J: [jJ];
fragment K: [kK];
fragment L: [lL];
fragment M: [mM];
fragment N: [nN];
fragment O: [oO];
fragment P: [pP];
fragment Q: [qQ];
fragment R: [rR];
fragment S: [sS];
fragment T: [tT];
fragment U: [uU];
fragment V: [vV];
fragment W: [wW];
fragment X: [xX];
fragment Y: [yY];
fragment Z: [zZ];

fragment LETTER: [a-zA-Z];
fragment OCT_DIGIT: [0-7];
fragment DEC_DIGIT: [0-9];
fragment HEX_DIGIT: [0-9a-fA-F];

ARROW: '->';
ASTERISK: '*';
BACKQUOTE: '`';
BACKSLASH: '\\';
COLON: ':';
COMMA: ',';
CONCAT: '||';
DASH: '-';
DOLLAR: '$';
DOT: '.';
EQ_DOUBLE: '==';
EQ_SINGLE: '=';
GT_EQ: '>=';
GT: '>';
HASH: '#';
IREGEX_SINGLE: '~*';
IREGEX_DOUBLE: '=~*';
LBRACE: '{' -> pushMode(DEFAULT_MODE);
LBRACKET: '[';
LPAREN: '(';
LT_EQ: '<=';
TAG_LT_SLASH: '</' -> type(LT_SLASH), pushMode(HOGQLX_TAG_CLOSE);
TAG_LT_OPEN: '<' {isOpeningTag()}? -> type(LT), pushMode(HOGQLX_TAG_OPEN);
LT: '<';
LT_SLASH: '</';
NOT_EQ: '!=' | '<>';
NOT_IREGEX: '!~*';
NOT_REGEX: '!~';
NULL_PROPERTY: '?.';
NULLISH: '??';
PERCENT: '%';
PLUS: '+';
QUERY: '?';
QUOTE_DOUBLE: '"';
QUOTE_SINGLE_TEMPLATE: 'f\'' -> pushMode(IN_TEMPLATE_STRING); // start of regular f'' template strings
QUOTE_SINGLE_TEMPLATE_FULL: 'F\'' -> pushMode(IN_FULL_TEMPLATE_STRING); // magic F' symbol used to parse "full text" templates
QUOTE_SINGLE: '\'';
REGEX_SINGLE: '~';
REGEX_DOUBLE: '=~';
RBRACE: '}' -> popMode;
RBRACKET: ']';
RPAREN: ')';
SEMICOLON: ';';
SLASH: '/';
SLASH_GT: '/>';
UNDERSCORE: '_';

// Comments and whitespace
MULTI_LINE_COMMENT: '/*' .*? '*/' -> skip;
SINGLE_LINE_COMMENT: ('--' | '//') ~('\n'|'\r')* ('\n' | '\r' | EOF) -> skip;
// whitespace is hidden and not skipped so that it's preserved in ANTLR errors like "no viable alternative"
WHITESPACE: [ \u000B\u000C\t\r\n] -> channel(HIDDEN);

// ───────── f' TEMPLATE STRING MODE ─────────
mode IN_TEMPLATE_STRING;
STRING_TEXT: ((~([\\'{])) | ESCAPE_CHAR_COMMON | BACKSLASH QUOTE_SINGLE | (BACKSLASH LBRACE) | (QUOTE_SINGLE QUOTE_SINGLE))+;
STRING_ESCAPE_TRIGGER: LBRACE -> pushMode(DEFAULT_MODE);
STRING_QUOTE_SINGLE: QUOTE_SINGLE -> type(QUOTE_SINGLE), popMode;

// ───────── F' FULL TEMPLATE STRING MODE ─────────
// a magic F' takes us to "full template strings" mode, where we don't need to escape single quotes and parse until EOF
// this can't be used within a normal columnExpr, but has to be parsed for separately
mode IN_FULL_TEMPLATE_STRING;
FULL_STRING_TEXT: ((~([{])) | ESCAPE_CHAR_COMMON | (BACKSLASH LBRACE))+;
FULL_STRING_ESCAPE_TRIGGER: LBRACE -> pushMode(DEFAULT_MODE);

// ───────── HOGQLX TAG MODE for opening/self-closing tags ─────────
mode HOGQLX_TAG_OPEN;

TAG_SELF_CLOSE_GT : '/>' -> type(SLASH_GT), popMode;   // <tag …/>
TAG_OPEN_GT       :  '>' -> type(GT), popMode, pushMode(HOGQLX_TEXT);   // <tag …>

// minimal token set; map everything back to the default token types
TAG_IDENT   : [a-zA-Z_][a-zA-Z0-9_-]* -> type(IDENTIFIER);
TAG_EQ      : '='                     -> type(EQ_SINGLE);
TAG_STRING  : STRING_LITERAL          -> type(STRING_LITERAL);
TAG_WS      : [ \t\r\n]+              -> channel(HIDDEN);
TAG_LBRACE  : '{'                     -> type(LBRACE), pushMode(DEFAULT_MODE);


// ───────── HOGQLX TAG MODE for closing tags ─────────
mode HOGQLX_TAG_CLOSE;

TAGC_GT     :  '>' -> type(GT), popMode;                // *** no TEXT push ***
TAGC_IDENT  : [a-zA-Z_][a-zA-Z0-9_-]* -> type(IDENTIFIER);
TAGC_WS     : [ \t\r\n]+              -> channel(HIDDEN);


// ───────── HOGQLX TEXT MODE ─────────
mode HOGQLX_TEXT;

HOGQLX_TEXT_TEXT
    : ~[<{]+ ; // everything except “{” or “<”

HOGQLX_TEXT_LBRACE
    : '{' -> type(LBRACE), pushMode(DEFAULT_MODE);

HOGQLX_TEXT_LT_SLASH
    : '</' -> type(LT_SLASH), popMode, pushMode(HOGQLX_TAG_CLOSE);

HOGQLX_TEXT_LT
    : '<' -> type(LT), pushMode(HOGQLX_TAG_OPEN);

HOGQLX_TEXT_WS
    : [ \t\r\n]+ -> channel(HIDDEN);

