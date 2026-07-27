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
COLUMNS: C O L U M N S;
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
EXCLUDE: E X C L U D E;
EXTRACT: E X T R A C T;
FINAL: F I N A L;
FILL: F I L L;
FILTER: F I L T E R;
FINALLY: F I N A L L Y;
FIRST: F I R S T;
FN: F N;
FOLLOWING: F O L L O W I N G;
FOR: F O R;
FROM: F R O M;
FULL: F U L L;
FUN: F U N;
GROUP: G R O U P;
GROUPING: G R O U P I N G;
HAVING: H A V I N G;
HOUR: H O U R;
ID: I D;
IF: I F;
ILIKE: I L I K E;
IGNORE: I G N O R E;
INCLUDE: I N C L U D E;
IN: I N;
INF: I N F | I N F I N I T Y;
INNER: I N N E R;
INTERSECT: I N T E R S E C T;
INTERPOLATE: I N T E R P O L A T E;
INTERVAL: I N T E R V A L;
IS: I S;
JOIN: J O I N;
KEY: K E Y;
LAMBDA: L A M B D A;
LAST: L A S T;
LEADING: L E A D I N G;
LEFT: L E F T;
LET: L E T;
LIKE: L I K E;
LIMIT: L I M I T;
MATERIALIZED: M A T E R I A L I Z E D;
MINUTE: M I N U T E;
MONTH: M O N T H;
NAME: N A M E;
NATURAL: N A T U R A L;
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
PIVOT: P I V O T;
POSITIONAL: P O S I T I O N A L;
PRECEDING: P R E C E D I N G;
PREWHERE: P R E W H E R E;
QUALIFY: Q U A L I F Y;
QUARTER: Q U A R T E R;
RANGE: R A N G E;
RECURSIVE: R E C U R S I V E;
REPLACE: R E P L A C E;
RETURN: R E T U R N;
RIGHT: R I G H T;
ROLLUP: R O L L U P;
ROW: R O W;
ROWS: R O W S;
SAMPLE: S A M P L E;
SECOND: S E C O N D;
SELECT: S E L E C T;
SEMI: S E M I;
SETS: S E T S;
SETTINGS: S E T T I N G S;
STEP: S T E P;
SUBSTRING: S U B S T R I N G;
THEN: T H E N;
THROW: T H R O W;
TIES: T I E S;
TIMESTAMP: T I M E S T A M P;
TIME: T I M E;
LOCAL: L O C A L;
ZONE: Z O N E;
TO: T O;
TOP: T O P;
TOTALS: T O T A L S;
TRAILING: T R A I L I N G;
TRIM: T R I M;
TRUNCATE: T R U N C A T E;
TRY: T R Y;
TRY_CAST: T R Y '_' C A S T;
UNBOUNDED: U N B O U N D E D;
UNION: U N I O N;
UNPIVOT: U N P I V O T;
USING: U S I N G;
VALUES: V A L U E S;
WEEK: W E E K;
WHEN: W H E N;
WHERE: W H E R E;
WHILE: W H I L E;
WINDOW: W I N D O W;
WITH: W I T H;
WITHIN: W I T H I N;
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
    | BACKSLASH BACKSLASH
    | BACKSLASH X HEX_DIGIT HEX_DIGIT;

IDENTIFIER
    : (LETTER | UNDERSCORE | DOLLAR) (LETTER | UNDERSCORE | DEC_DIGIT | DOLLAR)*
    ;
QUOTED_IDENTIFIER
    : BACKQUOTE ( ~([\\`]) | ESCAPE_CHAR_COMMON | BACKSLASH QUOTE_SINGLE | (BACKQUOTE BACKQUOTE) )* BACKQUOTE
    | QUOTE_DOUBLE ( ~([\\"]) | ESCAPE_CHAR_COMMON | BACKSLASH QUOTE_DOUBLE | (QUOTE_DOUBLE QUOTE_DOUBLE) )* QUOTE_DOUBLE
    ;
FLOATING_LITERAL
    // Hex-float exponent: strict C99 `p`/`P` only — `e`/`E` stays a hex digit, so `0x1e5` is 485, not a float.
    : HEXADECIMAL_LITERAL DOT HEX_DIGIT* P (PLUS | DASH)? DEC_DIGIT+
    | HEXADECIMAL_LITERAL P (PLUS | DASH)? DEC_DIGIT+
    | DECIMAL_LITERAL DOT DEC_DIGIT* E (PLUS | DASH)? DEC_DIGIT+
    | DOT DECIMAL_LITERAL E (PLUS | DASH)? DEC_DIGIT+
    | DECIMAL_LITERAL E (PLUS | DASH)? DEC_DIGIT+
    ;
// Binary literals (`0b1010`). Declared first so it wins the length-tie against MALFORMED_BINARY_LITERAL.
BINARY_LITERAL: '0' B BIN_DIGIT+;
OCTAL_LITERAL: '0' OCT_DIGIT+;
DECIMAL_LITERAL: DEC_DIGIT+;
HEXADECIMAL_LITERAL: '0' X HEX_DIGIT+;
// Postgres-16 `0o<digits>` octal — unsupported; lexed as a real token so the visitor can reject it clearly.
OCTAL_PREFIX_LITERAL: '0' [oO] DEC_DIGIT+;
// Malformed binary (`0b22`) BINARY_LITERAL didn't consume — caught so it can't re-tokenise as `0` + IDENTIFIER.
MALFORMED_BINARY_LITERAL: '0' [bB] DEC_DIGIT+;

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
fragment BIN_DIGIT: [01];
fragment OCT_DIGIT: [0-7];
fragment DEC_DIGIT: [0-9];
fragment HEX_DIGIT: [0-9a-fA-F];

ARROW: '->';
ASTERISK: '*';
BACKQUOTE: '`';
BACKSLASH: '\\';
DOUBLECOLON: '::';
COLONEQUALS: ':=';
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
NULL_SAFE_EQ: '<=>';
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
// MySQL-style `#` comments. `#<digit>` is excluded so positional references (`#1`) keep
// working — a `#` comment whose text starts with a digit is the one MySQL-ism this rejects.
HASH_COMMENT: '#' (~[0-9\n\r] ~[\n\r]*)? ('\n' | '\r' | EOF) -> skip;
// whitespace is hidden and not skipped so that it's preserved in ANTLR errors like "no viable alternative"
// The class is the full Unicode `White_Space` set, not just ASCII: a
// NO-BREAK SPACE or other Unicode space (often pasted in from rich
// editors or docs) is genuine whitespace and must keep separating
// tokens. Recognising it here keeps such programs valid — otherwise it
// would fall through to UNEXPECTED_CHARACTER below and fail the whole
// parse. U+FEFF (BOM) is included too, so a file saved with a
// byte-order mark still parses.
WHITESPACE: [ \t\r\n\u000B\u000C\u0085\u00A0\u1680\u2000-\u200A\u2028\u2029\u202F\u205F\u3000\uFEFF] -> channel(HIDDEN);

// Catch-all for any character no rule above matched. Without this the
// lexer raises a recoverable token-recognition error and DROPS the
// character — so stray input (a JavaScript `!`, `&&`, …) silently
// vanishes and the surrounding text parses as a different, valid-looking
// program. Emitting an explicit token instead means the parser has no
// rule for it and fails loudly with a SyntaxError. Listed last so it
// only ever fires as a true fallback (maximal munch keeps `!=`, `!~`,
// multi-character operators, comments, etc. intact).
UNEXPECTED_CHARACTER: . ;

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

// Skip comments between attributes — without these, the recoverable lexer error drops the delimiters and re-tokenises the body as phantom attributes.
TAG_MULTI_LINE_COMMENT  : '/*' .*? '*/'                                -> skip;
TAG_SINGLE_LINE_COMMENT : ('--' | '//') ~('\n'|'\r')* ('\n' | '\r' | EOF) -> skip;

// minimal token set; map everything back to the default token types
TAG_IDENT   : [a-zA-Z_][a-zA-Z0-9_-]* -> type(IDENTIFIER);
TAG_EQ      : '='                     -> type(EQ_SINGLE);
TAG_STRING  : STRING_LITERAL          -> type(STRING_LITERAL);
TAG_WS      : [ \t\r\n]+              -> channel(HIDDEN);
TAG_LBRACE  : '{'                     -> type(LBRACE), pushMode(DEFAULT_MODE);
// Catch-all for unmatched bytes (e.g. `#`, `&`, `@`) so the parser fails loudly instead of silently re-tokenising the surrounding text.
TAG_UNEXPECTED : . -> type(UNEXPECTED_CHARACTER);


// ───────── HOGQLX TAG MODE for closing tags ─────────
mode HOGQLX_TAG_CLOSE;

TAGC_GT     :  '>' -> type(GT), popMode;                // *** no TEXT push ***
TAGC_MULTI_LINE_COMMENT  : '/*' .*? '*/'                                -> skip;
TAGC_SINGLE_LINE_COMMENT : ('--' | '//') ~('\n'|'\r')* ('\n' | '\r' | EOF) -> skip;
TAGC_IDENT  : [a-zA-Z_][a-zA-Z0-9_-]* -> type(IDENTIFIER);
TAGC_WS     : [ \t\r\n]+              -> channel(HIDDEN);
TAGC_UNEXPECTED : . -> type(UNEXPECTED_CHARACTER);


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
