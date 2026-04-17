parser grammar HogQLParser;

options {
    tokenVocab = HogQLLexer;
}


program: declaration* EOF;

declaration: varDecl | statement ;

expression: columnExpr;

varDecl: LET identifier ( COLONEQUALS expression )? ;
identifierList: nestedIdentifier (COMMA nestedIdentifier)* COMMA?;

statement      : returnStmt
               | throwStmt
               | tryCatchStmt
               | ifStmt
               | whileStmt
               | forInStmt
               | forStmt
               | funcStmt
               | varAssignment
               | block
               | exprStmt
               | emptyStmt
               ;

returnStmt     : RETURN expression? SEMICOLON?;
throwStmt      : THROW expression? SEMICOLON?;
catchBlock     : CATCH (LPAREN catchVar=identifier (COLON catchType=identifier)? RPAREN)? catchStmt=block;
tryCatchStmt   : TRY tryStmt=block catchBlock* (FINALLY finallyStmt=block)?;
ifStmt         : IF LPAREN expression RPAREN statement ( ELSE statement )? ;
whileStmt      : WHILE LPAREN expression RPAREN statement SEMICOLON?;
forStmt        : FOR LPAREN
                 (initializerVarDeclr=varDecl | initializerVarAssignment=varAssignment | initializerExpression=expression)? SEMICOLON
                 condition=expression? SEMICOLON
                 (incrementVarDeclr=varDecl | incrementVarAssignment=varAssignment | incrementExpression=expression)?
                 RPAREN statement SEMICOLON?;
forInStmt      : FOR LPAREN LET identifier (COMMA identifier)? IN expression RPAREN statement SEMICOLON?;
funcStmt       : (FN | FUN) identifier LPAREN identifierList? RPAREN block;
varAssignment  : expression COLONEQUALS expression ;
exprStmt       : expression SEMICOLON?;
emptyStmt      : SEMICOLON ;
block          : LBRACE declaration* RBRACE ;

kvPair: expression ':' expression ;
kvPairList: kvPair (COMMA kvPair)* COMMA?;


// SELECT statement
select: (selectSetStmt | selectStmt | hogqlxTagElement) SEMICOLON? EOF;

selectStmtWithParens: selectStmt | withClause LPAREN selectSetStmt RPAREN | LPAREN selectSetStmt RPAREN | placeholder;

subsequentSelectSetClause: (EXCEPT ALL (BY NAME)? | EXCEPT (BY NAME)? | UNION ALL (BY NAME)? | UNION DISTINCT (BY NAME)? | UNION (BY NAME)? | INTERSECT ALL (BY NAME)? | INTERSECT DISTINCT (BY NAME)? | INTERSECT (BY NAME)?) selectStmtWithParens;
selectSetStmt: selectStmtWithParens (subsequentSelectSetClause)* orderByClause? limitAndOffsetClauseOptional?;
limitAndOffsetClauseOptional
    : LIMIT columnExpr PERCENT? (COMMA columnExpr)? (WITH TIES)?
    | LIMIT columnExpr PERCENT? (WITH TIES)? OFFSET columnExpr
    | OFFSET columnExpr
    ;

selectStmt:
    with=withClause?
    SELECT DISTINCT? topClause?
    columns=selectColumnExprListBeforeFrom
    from=fromClause?
    arrayJoinClause?
    prewhereClause?
    where=whereClause?
    (USING? sampleClause)?
    groupByClause? (WITH (CUBE | ROLLUP))? (WITH TOTALS)?
    havingClause?
    qualifyClause?
    (USING sampleClause)?
    windowClause?
    orderByClause?
    limitByClause?
    (limitAndOffsetClause | offsetOnlyClause)?
    settingsClause?
    ;

withClause: WITH RECURSIVE? withExprList;
topClause: TOP DECIMAL_LITERAL (WITH TIES)?;
fromClause: FROM joinExpr;
arrayJoinClause: (LEFT | INNER)? ARRAY JOIN columnExprList;
windowClause: WINDOW identifier AS LPAREN windowExpr RPAREN (COMMA identifier AS LPAREN windowExpr RPAREN)*;
prewhereClause: PREWHERE columnExpr;
whereClause: WHERE columnExpr;
groupByClause: GROUP BY (
    ALL
    | (CUBE | ROLLUP) LPAREN columnExprList RPAREN
    | GROUPING SETS LPAREN groupingSetList RPAREN
    | columnExprList
    );
groupingSetList: groupingSet (COMMA groupingSet)*;
groupingSet: LPAREN columnExprList? RPAREN;
havingClause: HAVING columnExpr;
qualifyClause: QUALIFY columnExpr;
orderByClause: ORDER BY orderExprList;
projectionOrderByClause: ORDER BY columnExprList;
limitByClause: LIMIT limitExpr BY columnExprList;
limitAndOffsetClause
    : LIMIT columnExpr PERCENT? (COMMA columnExpr)? (WITH TIES)? // compact OFFSET-optional form
    | LIMIT columnExpr PERCENT? (WITH TIES)? OFFSET columnExpr // verbose OFFSET-included form with WITH TIES
    ;
offsetOnlyClause: OFFSET columnExpr;
settingsClause: SETTINGS settingExprList;

valuesClause: VALUES valuesRow (COMMA valuesRow)*;
valuesRow: LPAREN columnExpr (COMMA columnExpr)* RPAREN;

joinExpr
    : joinExpr NATURAL? joinOp? JOIN joinExpr joinConstraintClause?  # JoinExprOp
    | joinExpr POSITIONAL JOIN joinExpr joinConstraintClause?                # JoinExprPositional
    | joinExpr joinOpCross joinExpr                                          # JoinExprCrossOp
    | joinExpr PIVOT LPAREN columnExprList pivotColumnList (GROUP BY columnExprList)? RPAREN  # JoinExprPivot
    | joinExpr UNPIVOT (INCLUDE NULLS)? LPAREN unpivotColumnList RPAREN      # JoinExprUnpivot
    | tableExpr FINAL? sampleClause?                                         # JoinExprTable
    | LPAREN joinExpr RPAREN                                                 # JoinExprParens
    ;
joinOp
    : ((ALL | ANY | ASOF)? INNER | INNER (ALL | ANY | ASOF)? | (ALL | ANY | ASOF) | ANTI | SEMI | ASOF (ANTI | SEMI))  # JoinOpInner
    | ( (SEMI | ALL | ANTI | ANY | ASOF)? (LEFT | RIGHT) OUTER?
      | (LEFT | RIGHT) OUTER? (SEMI | ALL | ANTI | ANY | ASOF)?
      | ASOF (ANTI | SEMI) (LEFT | RIGHT) OUTER?
      )                                                                             # JoinOpLeftRight
    | ((ALL | ANY | ASOF)? FULL OUTER? | FULL OUTER? (ALL | ANY | ASOF)?)           # JoinOpFull
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

sampleClause: SAMPLE ratioExpr PERCENT? (OFFSET ratioExpr)? (LPAREN identifier RPAREN)?;
limitExpr: columnExpr ((COMMA | OFFSET) columnExpr)?;
orderExprList: orderExpr (COMMA orderExpr)*;
orderExpr: columnExpr (ASCENDING | DESCENDING | DESC)? (NULLS (FIRST | LAST))? (COLLATE STRING_LITERAL)?;
ratioExpr: placeholder | numberLiteral (SLASH numberLiteral)?;
settingExprList: settingExpr (COMMA settingExpr)*;
settingExpr: identifier EQ_SINGLE literal;

windowExpr: winPartitionByClause? winOrderByClause? winFrameClause?;
winPartitionByClause: PARTITION BY columnExprList;
winOrderByClause: ORDER BY orderExprList;
withinGroupClause: WITHIN GROUP LPAREN orderByClause RPAREN;
winFrameClause: (ROWS | RANGE) winFrameExtend;
winFrameExtend
    : winFrameBound                             # frameStart
    | BETWEEN winFrameBound AND winFrameBound   # frameBetween
    ;
winFrameBound: (CURRENT ROW | UNBOUNDED PRECEDING | UNBOUNDED FOLLOWING | columnExpr PRECEDING | columnExpr FOLLOWING);
//rangeClause: RANGE LPAREN (MIN identifier MAX identifier | MAX identifier MIN identifier) RPAREN;

// Columns
expr: columnExpr EOF;
columnTypeExpr
    : columnTypeExpr LBRACKET DECIMAL_LITERAL? RBRACKET                                             # ColumnTypeExprArray    // INTEGER[], VARCHAR[3]
    | identifier LPAREN identifier columnTypeExpr (COMMA identifier columnTypeExpr)* COMMA? RPAREN  # ColumnTypeExprNested   // Nested
    | identifier LPAREN enumValue (COMMA enumValue)* COMMA? RPAREN                                  # ColumnTypeExprEnum     // Enum
    | identifier LPAREN columnTypeExpr (COMMA columnTypeExpr)* COMMA? RPAREN                        # ColumnTypeExprComplex  // Array, Tuple
    | identifier LPAREN columnExprList? RPAREN                                               # ColumnTypeExprParam    // FixedString(N)
    | identifier identifier+                                                                 # ColumnTypeExprCompound // TIME WITH TIME ZONE
    | identifier                                                                             # ColumnTypeExprSimple   // UInt64
    ;
// Restricted type expr for :: casts — no parenthesized variants to avoid ambiguity with function calls
columnTypeCastExpr
    : columnTypeCastIdentifier WITH LOCAL? TIME ZONE                                          # ColumnTypeCastExprWithTimeZone
    | columnTypeCastIdentifier                                                               # ColumnTypeCastExprSimple
    ;
columnTypeCastIdentifier
    : IDENTIFIER
    | QUOTED_IDENTIFIER
    | interval
    | keywordForTypeCast
    ;
keywordForTypeCast
    : DATE
    | TIME
    | TIMESTAMP
    | INTERVAL
    ;
columnExprList: columnExpr (COMMA columnExpr)* COMMA?;
selectColumnExprListBeforeFrom
    : selectColumnExpr (COMMA selectColumnExpr)* COMMA                                 # SelectColumnExprListBeforeFromTrailingComma
    | selectColumnExprList                                                              # SelectColumnExprListBeforeFromPlain
    ;
selectColumnExprList: selectColumnExpr (COMMA selectColumnExpr)* COMMA?;
selectColumnExpr
    : identifier COLON columnExpr                                                   # ColumnExprAliasBefore
    | FROM implicitAlias                                                             # ColumnExprInvalidFromImplicitAlias
    | columnExpr                                                                    # ColumnExprSelectValue
    | columnExpr implicitAlias                                                      # ColumnExprAliasImplicit
    ;
columnExpr
    : CASE caseExpr=columnExpr? (WHEN whenExpr=columnExpr THEN thenExpr=columnExpr)+ (ELSE elseExpr=columnExpr)? END          # ColumnExprCase
    | CAST LPAREN columnExpr AS columnTypeExpr RPAREN                                     # ColumnExprCast
    | TRY_CAST LPAREN columnExpr AS columnTypeExpr RPAREN                                 # ColumnExprTryCast
    | DATE STRING_LITERAL                                                                 # ColumnExprDate
//    | EXTRACT LPAREN interval FROM columnExpr RPAREN                                      # ColumnExprExtract   // Interferes with a function call
    | INTERVAL STRING_LITERAL                                                             # ColumnExprIntervalString
    | INTERVAL columnExpr interval                                                        # ColumnExprInterval
    | SUBSTRING LPAREN columnExpr FROM columnExpr (FOR columnExpr)? RPAREN                # ColumnExprSubstring
    | TIMESTAMP STRING_LITERAL                                                            # ColumnExprTimestamp
    | TRIM LPAREN (BOTH | LEADING | TRAILING) string FROM columnExpr RPAREN               # ColumnExprTrim
    | COLUMNS LPAREN STRING_LITERAL RPAREN                                                # ColumnExprColumnsRegex
    | COLUMNS LPAREN columnExprList RPAREN                                                # ColumnExprColumnsList
    | (COLUMNS LPAREN ASTERISK EXCLUDE LPAREN identifierList RPAREN REPLACE LPAREN columnsReplaceList RPAREN RPAREN
      | LPAREN ASTERISK EXCLUDE LPAREN identifierList RPAREN REPLACE LPAREN columnsReplaceList RPAREN RPAREN
      )                                                                                   # ColumnExprColumnsExcludeReplace
    | COLUMNS LPAREN ASTERISK EXCLUDE LPAREN identifierList RPAREN RPAREN                 # ColumnExprColumnsExclude
    | (COLUMNS LPAREN ASTERISK REPLACE LPAREN columnsReplaceList RPAREN RPAREN
      | LPAREN ASTERISK REPLACE LPAREN columnsReplaceList RPAREN RPAREN
      )                                                                                   # ColumnExprColumnsReplace
    | COLUMNS LPAREN ASTERISK RPAREN                                                      # ColumnExprColumnsAll
    | COLUMNS LPAREN identifier DOT ASTERISK EXCLUDE LPAREN identifierList RPAREN REPLACE LPAREN columnsReplaceList RPAREN RPAREN  # ColumnExprColumnsQualifiedExcludeReplace
    | COLUMNS LPAREN identifier DOT ASTERISK EXCLUDE LPAREN identifierList RPAREN RPAREN  # ColumnExprColumnsQualifiedExclude
    | COLUMNS LPAREN identifier DOT ASTERISK REPLACE LPAREN columnsReplaceList RPAREN RPAREN  # ColumnExprColumnsQualifiedReplace
    | COLUMNS LPAREN identifier DOT ASTERISK RPAREN                                       # ColumnExprColumnsQualifiedAll
    | ASTERISK COLUMNS LPAREN STRING_LITERAL RPAREN                                      # ColumnExprSpreadColumnsRegex
    | ASTERISK COLUMNS LPAREN columnExprList RPAREN                                      # ColumnExprSpreadColumnsList
    | identifier LPAREN columnExprs=columnExprList? RPAREN withinGroupClause                                                                        # ColumnExprFunctionWithinGroup
    | identifier (LPAREN columnExprs=columnExprList? RPAREN) (LPAREN DISTINCT? columnArgList=columnExprList? RPAREN)? (FILTER LPAREN WHERE filterExpr=columnExpr RPAREN)? OVER LPAREN windowExpr RPAREN # ColumnExprWinFunction
    | identifier (LPAREN columnExprs=columnExprList? RPAREN) (LPAREN DISTINCT? columnArgList=columnExprList? RPAREN)? (FILTER LPAREN WHERE filterExpr=columnExpr RPAREN)? OVER identifier               # ColumnExprWinFunctionTarget
    | identifier (LPAREN columnExprs=columnExprList? RPAREN)? LPAREN DISTINCT? columnArgList=columnExprList? (ORDER BY orderExprList)? RPAREN (FILTER LPAREN WHERE filterExpr=columnExpr RPAREN)?  # ColumnExprFunction
    | columnExpr LPAREN selectSetStmt RPAREN                                              # ColumnExprCallSelect
    | columnExpr LPAREN columnExprList? RPAREN                                            # ColumnExprCall
    | hogqlxTagElement                                                                    # ColumnExprTagElement
    | templateString                                                                      # ColumnExprTemplateString
    | literal                                                                             # ColumnExprLiteral

    // FIXME(ilezhankin): this part looks very ugly, maybe there is another way to express it
    | columnExpr LBRACKET columnExpr RBRACKET                                             # ColumnExprArrayAccess
    | columnExpr LBRACKET columnExpr? COLON columnExpr? RBRACKET                         # ColumnExprArraySlice
    | columnExpr DOT DECIMAL_LITERAL                                                      # ColumnExprTupleAccess
    | columnExpr DOT identifier                                                           # ColumnExprPropertyAccess
    | columnExpr NULL_PROPERTY LBRACKET columnExpr RBRACKET                               # ColumnExprNullArrayAccess
    | columnExpr NULL_PROPERTY DECIMAL_LITERAL                                            # ColumnExprNullTupleAccess
    | columnExpr NULL_PROPERTY identifier                                                 # ColumnExprNullPropertyAccess
    | columnExpr DOUBLECOLON columnTypeCastExpr                                            # ColumnExprTypeCast
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
    | columnExpr IGNORE NULLS                                                            # ColumnExprIgnoreNulls
    | columnExpr IS NOT? NULL_SQL                                                         # ColumnExprIsNull
    | columnExpr IS NOT? DISTINCT FROM columnExpr                                         # ColumnExprIsDistinctFrom
    | columnExpr NULLISH columnExpr                                                       # ColumnExprNullish
    | NOT columnExpr                                                                      # ColumnExprNot
    | columnExpr AND columnExpr                                                           # ColumnExprAnd
    | columnExpr OR columnExpr                                                            # ColumnExprOr
    // TODO(ilezhankin): `BETWEEN a AND b AND c` is parsed in a wrong way: `BETWEEN (a AND b) AND c`
    | columnExpr NOT? BETWEEN columnExpr AND columnExpr                                   # ColumnExprBetween
    | <assoc=right> columnExpr QUERY columnExpr COLON columnExpr                          # ColumnExprTernaryOp
    | columnExpr AS (identifier | STRING_LITERAL)                                         # ColumnExprAlias
    | (tableIdentifier DOT)? ASTERISK (EXCLUDE LPAREN identifierList RPAREN)?             # ColumnExprAsterisk  // single-column only
    | LAMBDA identifier (COMMA identifier)* COMMA? COLON columnExpr                       # ColumnExprColonLambda
    | LPAREN selectSetStmt RPAREN                                                         # ColumnExprSubquery  // single-column only
    | LPAREN columnExpr RPAREN                                                            # ColumnExprParens    // single-column only
    | LPAREN columnExprList RPAREN                                                        # ColumnExprTuple
    | ARRAY? LBRACKET columnExprList? RBRACKET                                              # ColumnExprArray
    | LBRACE (kvPairList)? RBRACE                                                         # ColumnExprDict
    | columnLambdaExpr                                                                    # ColumnExprLambda
    | identifier COLONEQUALS columnExpr                                                   # ColumnExprNamedArg
    | HASH DECIMAL_LITERAL                                                                # ColumnExprPositional
    | columnIdentifier                                                                    # ColumnExprIdentifier
    ;

columnLambdaExpr:
    ( LPAREN identifier (COMMA identifier)* COMMA? RPAREN
    |        identifier (COMMA identifier)* COMMA?
    | LPAREN RPAREN
    )
    ARROW (columnExpr | block)                                                              # ArrowLambda
    | LAMBDA identifier (COMMA identifier)* COMMA? COLON columnExpr                        # ColonLambda
    ;

columnsReplaceList: columnsReplaceItem (COMMA columnsReplaceItem)*;
columnsReplaceItem: columnExpr AS identifier;

hogqlxChildElement
    : hogqlxTagElement
    | hogqlxText
    | LBRACE columnExpr RBRACE;

hogqlxText : HOGQLX_TEXT_TEXT ;

hogqlxTagElement
    : LT identifier hogqlxTagAttribute* SLASH_GT                                          # HogqlxTagElementClosed
    | LT identifier hogqlxTagAttribute* GT hogqlxChildElement* LT_SLASH identifier GT     # HogqlxTagElementNested
    ;
hogqlxTagAttribute
    :   identifier EQ_SINGLE string
    |   identifier EQ_SINGLE LBRACE columnExpr RBRACE
    |   identifier
    ;

withExprList: withExpr (COMMA withExpr)* COMMA?;
withExpr
    : identifier withExprColumnNameList? (USING KEY withExprColumnNameList)? AS (NOT? MATERIALIZED)? LPAREN selectSetStmt RPAREN    # WithExprSubquery
    // NOTE: asterisk and subquery goes before |columnExpr| so that we can mark them as multi-column expressions.
    | columnExpr AS identifier                                          # WithExprColumn
    ;

withExprColumnNameList: LPAREN identifier (COMMA identifier)* RPAREN;


// This is slightly different in HogQL compared to ClickHouse SQL
// HogQL allows unlimited ("*") nestedIdentifier-s "properties.b.a.a.w.a.s".
// We parse and convert "databaseIdentifier.tableIdentifier.columnIdentifier.nestedIdentifier.*"
// to just one ast.Field(chain=['a','b','columnIdentifier','on','and','on']).
columnIdentifier: placeholder | ((tableIdentifier DOT)? nestedIdentifier);
nestedIdentifier: identifier (DOT identifier)*;
tableExpr
    : tableIdentifier                                   # TableExprIdentifier
    | tableFunctionExpr                                 # TableExprFunction
    | LPAREN selectSetStmt RPAREN                       # TableExprSubquery
    | LPAREN valuesClause RPAREN                        # TableExprValues
    | tableExpr PIVOT LPAREN columnExprList pivotColumnList (GROUP BY columnExprList)? RPAREN # TableExprPivot
    | tableExpr UNPIVOT (INCLUDE NULLS)? LPAREN unpivotColumnList RPAREN # TableExprUnpivot
    | tableExpr (alias | AS identifier) columnAliases?  # TableExprAlias
    | hogqlxTagElement                                  # TableExprTag
    | placeholder                                       # TableExprPlaceholder
    ;

pivotColumnList: FOR pivotColumn+;
pivotColumn: columnExprTupleOrSingle IN LPAREN columnExprList RPAREN;
unpivotColumnList: unpivotColumn (COMMA unpivotColumn)* COMMA?;
unpivotColumn: columnExprTupleOrSingle FOR columnExprTupleOrSingle IN LPAREN columnExprList RPAREN (columnExprTupleOrSingle IN LPAREN columnExprList RPAREN)*;
columnExprTupleOrSingle: LPAREN columnExprList RPAREN | columnExpr;
columnAliases: LPAREN identifier (COMMA identifier)* RPAREN;
tableFunctionExpr: identifier LPAREN tableArgList? RPAREN;
tableIdentifier: (databaseIdentifier DOT)? nestedIdentifier;
tableArgList: columnExpr (COMMA columnExpr)* COMMA?;

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
    : ALL | AND | ANTI | ANY | ARRAY | AS | ASCENDING | ASOF | BETWEEN | BOTH | BY | CASE
    | CAST | COHORT | COLLATE | COLUMNS | CROSS | CUBE | CURRENT | DATE | DESC | DESCENDING
    | DISTINCT | ELSE | END | EXCLUDE | EXTRACT | FILTER | FINAL | FIRST
    | FOR | FOLLOWING | FROM | FULL | GROUP | HAVING | ID | IS
    | GROUPING | IF | IGNORE | ILIKE | INCLUDE | IN | INNER | INTERVAL | JOIN | KEY
    | LAMBDA | LAST | LEADING | LEFT | LIKE | LIMIT
    | LOCAL | NAME | NATURAL | NOT | NULLS | OFFSET | ON | OR | ORDER | OUTER | OVER | PARTITION
    | PIVOT | POSITIONAL | PRECEDING | PREWHERE | QUALIFY | RANGE | RECURSIVE | REPLACE | RETURN | RIGHT | ROLLUP | ROW
    | ROWS | SAMPLE | SELECT | SEMI | SETS | SETTINGS | SUBSTRING
    | THEN | TIES | TIME | TIMESTAMP | TOTALS | TRAILING | TRIM | TRUNCATE | TRY_CAST | TO | TOP
    | UNBOUNDED | UNION | UNPIVOT | USING | VALUES | WHEN | WHERE | WINDOW | WITH
    | ZONE
    ;
keywordForAlias
    : DATE | FIRST | ID | KEY
    ;
keywordForImplicitAlias
    : ASCENDING
    | COHORT
    | DATE
    | DESCENDING
    | FINAL
    | ID
    | RETURN
    | TOP
    | TOTALS
    ;
alias: IDENTIFIER | QUOTED_IDENTIFIER | keywordForAlias;  // |interval| can't be an alias, otherwise 'INTERVAL 1 SOMETHING' becomes ambiguous.
implicitAlias: IDENTIFIER | QUOTED_IDENTIFIER | keywordForImplicitAlias;
identifier: IDENTIFIER | QUOTED_IDENTIFIER | interval | keyword;
enumValue: string EQ_SINGLE numberLiteral;
placeholder: LBRACE columnExpr RBRACE;

string: STRING_LITERAL | templateString;
templateString : QUOTE_SINGLE_TEMPLATE stringContents* QUOTE_SINGLE ;
stringContents : STRING_ESCAPE_TRIGGER columnExpr RBRACE | STRING_TEXT;

// These are magic "full template strings", which are used to parse "full text field" templates without the surrounding SQL.
// We will need to add F' to the start of the string to change the lexer's mode.
fullTemplateString: QUOTE_SINGLE_TEMPLATE_FULL stringContentsFull* EOF ;
stringContentsFull : FULL_STRING_ESCAPE_TRIGGER columnExpr RBRACE | FULL_STRING_TEXT;
