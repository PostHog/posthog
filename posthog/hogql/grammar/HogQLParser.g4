parser grammar HogQLParser;

options {
    tokenVocab = HogQLLexer;
}

// SELECT statement
select: (selectUnionStmt | selectStmt) EOF;

selectUnionStmt: selectStmtWithParens (UNION ALL selectStmtWithParens)*;
selectStmtWithParens: selectStmt | LPAREN selectUnionStmt RPAREN;
selectStmt:
    with=withClause?
    SELECT DISTINCT? topClause?
    columns=columnExprList
    from=fromClause?
    arrayJoinClause?
    windowClause?
    prewhereClause?
    where=whereClause?
    groupByClause? (WITH (CUBE | ROLLUP))? (WITH TOTALS)?
    havingClause?
    orderByClause?
    limitClause?
    settingsClause?
    ;

withClause: WITH columnExprList;
topClause: TOP DECIMAL_LITERAL (WITH TIES)?;
fromClause: FROM joinExpr;
arrayJoinClause: (LEFT | INNER)? ARRAY JOIN columnExprList;
windowClause: WINDOW identifier AS LPAREN windowExpr RPAREN;
prewhereClause: PREWHERE columnExpr;
whereClause: WHERE columnExpr;
groupByClause: GROUP BY ((CUBE | ROLLUP) LPAREN columnExprList RPAREN | columnExprList);
havingClause: HAVING columnExpr;
orderByClause: ORDER BY orderExprList;
projectionOrderByClause: ORDER BY columnExprList;
limitClause: LIMIT limitExpr ((WITH TIES) | BY columnExprList)?;
settingsClause: SETTINGS settingExprList;

joinExpr
    : joinExpr (GLOBAL | LOCAL)? joinOp? JOIN joinExpr joinConstraintClause  # JoinExprOp
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
    : (GLOBAL|LOCAL)? CROSS JOIN
    | COMMA
    ;
joinConstraintClause
    : ON columnExprList
    | USING LPAREN columnExprList RPAREN
    | USING columnExprList
    ;

sampleClause: SAMPLE ratioExpr (OFFSET ratioExpr)?;
limitExpr: columnExpr ((COMMA | OFFSET) columnExpr)?;
orderExprList: orderExpr (COMMA orderExpr)*;
orderExpr: columnExpr (ASCENDING | DESCENDING | DESC)? (NULLS (FIRST | LAST))? (COLLATE STRING_LITERAL)?;
ratioExpr: numberLiteral (SLASH numberLiteral)?;
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
columnExprList: columnsExpr (COMMA columnsExpr)*;
columnsExpr
    : (tableIdentifier DOT)? ASTERISK  # ColumnsExprAsterisk
    | LPAREN selectUnionStmt RPAREN    # ColumnsExprSubquery
    // NOTE: asterisk and subquery goes before |columnExpr| so that we can mark them as multi-column expressions.
    | columnExpr                       # ColumnsExprColumn
    ;
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
    | literal                                                                             # ColumnExprLiteral

    // FIXME(ilezhankin): this part looks very ugly, maybe there is another way to express it
    | columnExpr LBRACKET columnExpr RBRACKET                                             # ColumnExprArrayAccess
    | columnExpr DOT DECIMAL_LITERAL                                                      # ColumnExprTupleAccess
    | DASH columnExpr                                                                     # ColumnExprNegate
    | left=columnExpr ( operator=ASTERISK                                                               // multiply
                 | operator=SLASH                                                                  // divide
                 | operator=PERCENT                                                                // modulo
                 ) right=columnExpr                                                             # ColumnExprPrecedence1
    | left=columnExpr ( operator=PLUS                                                                   // plus
                 | operator=DASH                                                                   // minus
                 | operator=CONCAT                                                                 // concat
                 ) right=columnExpr                                                             # ColumnExprPrecedence2
    | left=columnExpr ( operator=EQ_DOUBLE                                                              // equals
                 | operator=EQ_SINGLE                                                              // equals
                 | operator=NOT_EQ                                                                 // notEquals
                 | operator=LE                                                                     // lessOrEquals
                 | operator=GE                                                                     // greaterOrEquals
                 | operator=LT                                                                     // less
                 | operator=GT                                                                     // greater
                 | operator=GLOBAL? NOT? IN                                                        // in, notIn, globalIn, globalNotIn
                 | operator=NOT? (LIKE | ILIKE)                                                    // like, notLike, ilike, notILike
                 ) right=columnExpr                                                             # ColumnExprPrecedence3
    | columnExpr IS NOT? NULL_SQL                                                         # ColumnExprIsNull
    | NOT columnExpr                                                                      # ColumnExprNot
    | columnExpr AND columnExpr                                                           # ColumnExprAnd
    | columnExpr OR columnExpr                                                            # ColumnExprOr
    // TODO(ilezhankin): `BETWEEN a AND b AND c` is parsed in a wrong way: `BETWEEN (a AND b) AND c`
    | columnExpr NOT? BETWEEN columnExpr AND columnExpr                                   # ColumnExprBetween
    | <assoc=right> columnExpr QUERY columnExpr COLON columnExpr                          # ColumnExprTernaryOp
    // Note: difference with Clickhouse: we also support "AS STRING_LITERAL" as a shortcut for naming columns
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

// This is slightly different in HogQL compared to ClickHouse SQL
// HogQL allows unlimited ("*") nestedIdentifier-s "properties.b.a.a.w.a.s".
// We parse and convert "databaseIdentifier.tableIdentifier.columnIdentifier.nestedIdentifier.*"
// to just one ast.Field(chain=['a','b','columnIdentifier','on','and','on']).
columnIdentifier: PLACEHOLDER | ((tableIdentifier DOT)? nestedIdentifier);
nestedIdentifier: identifier (DOT identifier)*;
tableExpr
    : tableIdentifier                    # TableExprIdentifier
    | tableFunctionExpr                  # TableExprFunction
    | LPAREN selectUnionStmt RPAREN      # TableExprSubquery
    | tableExpr (alias | AS identifier)  # TableExprAlias
    ;
tableFunctionExpr: identifier LPAREN tableArgList? RPAREN;
tableIdentifier: (databaseIdentifier DOT)? identifier;
tableArgList: tableArgExpr (COMMA tableArgExpr)*;
tableArgExpr
    : nestedIdentifier
    | tableFunctionExpr
    | literal
    ;

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
identifierOrNull: identifier | NULL_SQL;  // NULL_SQL can be only 'Null' here.
enumValue: STRING_LITERAL EQ_SINGLE numberLiteral;
