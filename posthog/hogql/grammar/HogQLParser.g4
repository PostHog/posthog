parser grammar HogQLParser;

options {
    tokenVocab = HogQLLexer;
}


// SELECT statement
select: (selectUnionStmt | selectStmt | hogqlxTagElement) EOF;

selectUnionStmt: selectStmtWithParens (UNION ALL selectStmtWithParens)*;
selectStmtWithParens: selectStmt | LPAREN selectUnionStmt RPAREN | placeholder;

selectStmt:
    with=withClause?
    SELECT DISTINCT? topClause?
    columns=columnExprList
    from=fromClause?
    arrayJoinClause?
    prewhereClause?
    where=whereClause?
    groupByClause? (WITH (CUBE | ROLLUP))? (WITH TOTALS)?
    havingClause?
    windowClause?
    orderByClause?
    (limitAndOffsetClause | offsetOnlyClause)?
    settingsClause?
    ;

withClause: WITH withExprList;
topClause: TOP DECIMAL_LITERAL (WITH TIES)?;
fromClause: FROM joinExpr;
arrayJoinClause: (LEFT | INNER)? ARRAY JOIN columnExprList;
windowClause: WINDOW identifier AS LPAREN windowExpr RPAREN (COMMA identifier AS LPAREN windowExpr RPAREN)*;
prewhereClause: PREWHERE columnExpr;
whereClause: WHERE columnExpr;
groupByClause: GROUP BY ((CUBE | ROLLUP) LPAREN columnExprList RPAREN | columnExprList);
havingClause: HAVING columnExpr;
orderByClause: ORDER BY orderExprList;
projectionOrderByClause: ORDER BY columnExprList;
limitAndOffsetClause
    : LIMIT columnExpr (COMMA columnExpr)? ((WITH TIES) | BY columnExprList)? // compact OFFSET-optional form
    | LIMIT columnExpr (WITH TIES)? OFFSET columnExpr // verbose OFFSET-included form with WITH TIES
    | LIMIT columnExpr OFFSET columnExpr (BY columnExprList)? // verbose OFFSET-included form with BY
    ;
offsetOnlyClause: OFFSET columnExpr;
settingsClause: SETTINGS settingExprList;

joinExpr
    : joinExpr joinOp? JOIN joinExpr joinConstraintClause  # JoinExprOp
    | joinExpr joinOpCross joinExpr                                          # JoinExprCrossOp
    | tableExpr FINAL? sampleClause?                                         # JoinExprTable
    | LPAREN joinExpr RPAREN                                                 # JoinExprParens
    ;
joinOp
    : ((ALL | ANY | ASOF)? INNER | INNER (ALL | ANY | ASOF)? | (ALL | ANY | ASOF))  # JoinOpInner
    | ( (SEMI | ALL | ANTI | ANY | ASOF)? (LEFT | RIGHT) OUTER?
      | (LEFT | RIGHT) OUTER? (SEMI | ALL | ANTI | ANY | ASOF)?
      )                                                                             # JoinOpLeftRight
    | ((ALL | ANY)? FULL OUTER? | FULL OUTER? (ALL | ANY)?)                         # JoinOpFull
    ;
joinOpCross
    : CROSS JOIN
    | COMMA
    ;
joinConstraintClause
    : ON columnExprList
    | USING LPAREN columnExprList RPAREN
    | USING columnExprList
    ;

sampleClause: SAMPLE ratioExpr (OFFSET ratioExpr)?;
orderExprList: orderExpr (COMMA orderExpr)*;
orderExpr: columnExpr (ASCENDING | DESCENDING | DESC)? (NULLS (FIRST | LAST))? (COLLATE STRING_LITERAL)?;
ratioExpr: placeholder | numberLiteral (SLASH numberLiteral)?;
settingExprList: settingExpr (COMMA settingExpr)*;
settingExpr: identifier EQ_SINGLE literal;

windowExpr: winPartitionByClause? winOrderByClause? winFrameClause?;
winPartitionByClause: PARTITION BY columnExprList;
winOrderByClause: ORDER BY orderExprList;
winFrameClause: (ROWS | RANGE) winFrameExtend;
winFrameExtend
    : winFrameBound                             # frameStart
    | BETWEEN winFrameBound AND winFrameBound   # frameBetween
    ;
winFrameBound: (CURRENT ROW | UNBOUNDED PRECEDING | UNBOUNDED FOLLOWING | numberLiteral PRECEDING | numberLiteral FOLLOWING);
//rangeClause: RANGE LPAREN (MIN identifier MAX identifier | MAX identifier MIN identifier) RPAREN;



// Columns
expr: columnExpr EOF;
columnTypeExpr
    : identifier                                                                             # ColumnTypeExprSimple   // UInt64
    | identifier LPAREN identifier columnTypeExpr (COMMA identifier columnTypeExpr)* RPAREN  # ColumnTypeExprNested   // Nested
    | identifier LPAREN enumValue (COMMA enumValue)* RPAREN                                  # ColumnTypeExprEnum     // Enum
    | identifier LPAREN columnTypeExpr (COMMA columnTypeExpr)* RPAREN                        # ColumnTypeExprComplex  // Array, Tuple
    | identifier LPAREN columnExprList? RPAREN                                               # ColumnTypeExprParam    // FixedString(N)
    ;
columnExprList: columnExpr (COMMA columnExpr)*;
columnExpr
    : CASE caseExpr=columnExpr? (WHEN whenExpr=columnExpr THEN thenExpr=columnExpr)+ (ELSE elseExpr=columnExpr)? END          # ColumnExprCase
    | CAST LPAREN columnExpr AS columnTypeExpr RPAREN                                     # ColumnExprCast
    | DATE STRING_LITERAL                                                                 # ColumnExprDate
    | EXTRACT LPAREN interval FROM columnExpr RPAREN                                      # ColumnExprExtract
    | INTERVAL columnExpr interval                                                        # ColumnExprInterval
    | SUBSTRING LPAREN columnExpr FROM columnExpr (FOR columnExpr)? RPAREN                # ColumnExprSubstring
    | TIMESTAMP STRING_LITERAL                                                            # ColumnExprTimestamp
    | TRIM LPAREN (BOTH | LEADING | TRAILING) STRING_LITERAL FROM columnExpr RPAREN       # ColumnExprTrim
    | identifier (LPAREN columnExprList? RPAREN) OVER LPAREN windowExpr RPAREN            # ColumnExprWinFunction
    | identifier (LPAREN columnExprList? RPAREN) OVER identifier                          # ColumnExprWinFunctionTarget
    | identifier (LPAREN columnExprList? RPAREN)? LPAREN DISTINCT? columnArgList? RPAREN  # ColumnExprFunction
    | hogqlxTagElement                                                                    # ColumnExprTagElement
    | literal                                                                             # ColumnExprLiteral

    // FIXME(ilezhankin): this part looks very ugly, maybe there is another way to express it
    | columnExpr LBRACKET columnExpr RBRACKET                                             # ColumnExprArrayAccess
    | columnExpr DOT DECIMAL_LITERAL                                                      # ColumnExprTupleAccess
    | columnExpr DOT identifier                                                           # ColumnExprPropertyAccess
    | DASH columnExpr                                                                     # ColumnExprNegate
    | left=columnExpr ( operator=ASTERISK                                                 // *
                 | operator=SLASH                                                         // /
                 | operator=PERCENT                                                       // %
                 ) right=columnExpr                                                       # ColumnExprPrecedence1
    | left=columnExpr ( operator=PLUS                                                     // +
                 | operator=DASH                                                          // -
                 | operator=CONCAT                                                        // ||
                 ) right=columnExpr                                                       # ColumnExprPrecedence2
    | left=columnExpr ( operator=EQ_DOUBLE                                                // =
                 | operator=EQ_SINGLE                                                     // ==
                 | operator=NOT_EQ                                                        // !=
                 | operator=LT_EQ                                                         // <=
                 | operator=LT                                                            // <
                 | operator=GT_EQ                                                         // >=
                 | operator=GT                                                            // >
                 | operator=NOT? IN COHORT?                                               // in, not in; in cohort; not in cohort
                 | operator=NOT? (LIKE | ILIKE)                                           // like, not like, ilike, not ilike
                 | operator=REGEX_SINGLE                                                  // ~
                 | operator=REGEX_DOUBLE                                                  // =~
                 | operator=NOT_REGEX                                                     // !~
                 | operator=IREGEX_SINGLE                                                 // ~*
                 | operator=IREGEX_DOUBLE                                                 // =~*
                 | operator=NOT_IREGEX                                                    // !~*
                 ) right=columnExpr                                                       # ColumnExprPrecedence3
    | columnExpr IS NOT? NULL_SQL                                                         # ColumnExprIsNull
    | columnExpr NULLISH columnExpr                                                       # ColumnExprNullish
    | NOT columnExpr                                                                      # ColumnExprNot
    | columnExpr AND columnExpr                                                           # ColumnExprAnd
    | columnExpr OR columnExpr                                                            # ColumnExprOr
    // TODO(ilezhankin): `BETWEEN a AND b AND c` is parsed in a wrong way: `BETWEEN (a AND b) AND c`
    | columnExpr NOT? BETWEEN columnExpr AND columnExpr                                   # ColumnExprBetween
    | <assoc=right> columnExpr QUERY columnExpr COLON columnExpr                          # ColumnExprTernaryOp
    // Note: difference with ClickHouse: we also support "AS STRING_LITERAL" as a shortcut for naming columns
    | columnExpr (alias | AS identifier | AS STRING_LITERAL)                              # ColumnExprAlias

    | (tableIdentifier DOT)? ASTERISK                                                     # ColumnExprAsterisk  // single-column only
    | LPAREN selectUnionStmt RPAREN                                                       # ColumnExprSubquery  // single-column only
    | LPAREN columnExpr RPAREN                                                            # ColumnExprParens    // single-column only
    | LPAREN columnExprList RPAREN                                                        # ColumnExprTuple
    | LBRACKET columnExprList? RBRACKET                                                   # ColumnExprArray
    | columnIdentifier                                                                    # ColumnExprIdentifier
    ;
columnArgList: columnArgExpr (COMMA columnArgExpr)*;
columnArgExpr: columnLambdaExpr | columnExpr;
columnLambdaExpr:
    ( LPAREN identifier (COMMA identifier)* RPAREN
    |        identifier (COMMA identifier)*
    )
    ARROW columnExpr
    ;


hogqlxTagElement
    : LT identifier hogqlxTagAttribute* SLASH GT                                        # HogqlxTagElementClosed
    | LT identifier hogqlxTagAttribute* GT hogqlxTagElement? LT SLASH identifier GT     # HogqlxTagElementNested
    ;
hogqlxTagAttribute
    :   identifier '=' STRING_LITERAL
    |   identifier '=' LBRACE columnExpr RBRACE
    |   identifier
    ;

withExprList: withExpr (COMMA withExpr)*;
withExpr
    : identifier AS LPAREN selectUnionStmt RPAREN    # WithExprSubquery
    // NOTE: asterisk and subquery goes before |columnExpr| so that we can mark them as multi-column expressions.
    | columnExpr AS identifier                       # WithExprColumn
    ;


// This is slightly different in HogQL compared to ClickHouse SQL
// HogQL allows unlimited ("*") nestedIdentifier-s "properties.b.a.a.w.a.s".
// We parse and convert "databaseIdentifier.tableIdentifier.columnIdentifier.nestedIdentifier.*"
// to just one ast.Field(chain=['a','b','columnIdentifier','on','and','on']).
columnIdentifier: placeholder | ((tableIdentifier DOT)? nestedIdentifier);
nestedIdentifier: identifier (DOT identifier)*;
tableExpr
    : tableIdentifier                    # TableExprIdentifier
    | tableFunctionExpr                  # TableExprFunction
    | LPAREN selectUnionStmt RPAREN      # TableExprSubquery
    | tableExpr (alias | AS identifier)  # TableExprAlias
    | hogqlxTagElement                   # TableExprTag
    | placeholder                        # TableExprPlaceholder
    ;
tableFunctionExpr: identifier LPAREN tableArgList? RPAREN;
tableIdentifier: (databaseIdentifier DOT)? identifier;
tableArgList: columnExpr (COMMA columnExpr)*;

// Databases

databaseIdentifier: identifier;

// Basics

floatingLiteral
    : FLOATING_LITERAL
    | DOT (DECIMAL_LITERAL | OCTAL_LITERAL)
    | DECIMAL_LITERAL DOT (DECIMAL_LITERAL | OCTAL_LITERAL)?  // can't move this to the lexer or it will break nested tuple access: t.1.2
    ;
numberLiteral: (PLUS | DASH)? (floatingLiteral | OCTAL_LITERAL | DECIMAL_LITERAL | HEXADECIMAL_LITERAL | INF | NAN_SQL);
literal
    : numberLiteral
    | STRING_LITERAL
    | NULL_SQL
    ;
interval: SECOND | MINUTE | HOUR | DAY | WEEK | MONTH | QUARTER | YEAR;
keyword
    // except NULL_SQL, INF, NAN_SQL
    : AFTER | ALIAS | ALL | ALTER | AND | ANTI | ANY | ARRAY | AS | ASCENDING | ASOF | AST | ASYNC | ATTACH | BETWEEN | BOTH | BY | CASE
    | CAST | CHECK | CLEAR | CLUSTER | CODEC | COLLATE | COLUMN | COMMENT | CONSTRAINT | CREATE | CROSS | CUBE | CURRENT | DATABASE
    | DATABASES | DATE | DEDUPLICATE | DEFAULT | DELAY | DELETE | DESCRIBE | DESC | DESCENDING | DETACH | DICTIONARIES | DICTIONARY | DISK
    | DISTINCT | DISTRIBUTED | DROP | ELSE | END | ENGINE | EVENTS | EXISTS | EXPLAIN | EXPRESSION | EXTRACT | FETCHES | FINAL | FIRST
    | FLUSH | FOR | FOLLOWING | FOR | FORMAT | FREEZE | FROM | FULL | FUNCTION | GLOBAL | GRANULARITY | GROUP | HAVING | HIERARCHICAL | ID
    | IF | ILIKE | IN | INDEX | INJECTIVE | INNER | INSERT | INTERVAL | INTO | IS | IS_OBJECT_ID | JOIN | JSON_FALSE | JSON_TRUE | KEY
    | KILL | LAST | LAYOUT | LEADING | LEFT | LIFETIME | LIKE | LIMIT | LIVE | LOCAL | LOGS | MATERIALIZE | MATERIALIZED | MAX | MERGES
    | MIN | MODIFY | MOVE | MUTATION | NO | NOT | NULLS | OFFSET | ON | OPTIMIZE | OR | ORDER | OUTER | OUTFILE | OVER | PARTITION
    | POPULATE | PRECEDING | PREWHERE | PRIMARY | RANGE | RELOAD | REMOVE | RENAME | REPLACE | REPLICA | REPLICATED | RIGHT | ROLLUP | ROW
    | ROWS | SAMPLE | SELECT | SEMI | SENDS | SET | SETTINGS | SHOW | SOURCE | START | STOP | SUBSTRING | SYNC | SYNTAX | SYSTEM | TABLE
    | TABLES | TEMPORARY | TEST | THEN | TIES | TIMEOUT | TIMESTAMP | TOTALS | TRAILING | TRIM | TRUNCATE | TO | TOP | TTL | TYPE
    | UNBOUNDED | UNION | UPDATE | USE | USING | UUID | VALUES | VIEW | VOLUME | WATCH | WHEN | WHERE | WINDOW | WITH
    ;
keywordForAlias
    : DATE | FIRST | ID | KEY
    ;
alias: IDENTIFIER | keywordForAlias;  // |interval| can't be an alias, otherwise 'INTERVAL 1 SOMETHING' becomes ambiguous.
identifier: IDENTIFIER | interval | keyword;
enumValue: STRING_LITERAL EQ_SINGLE numberLiteral;
placeholder: LBRACE identifier RBRACE;
