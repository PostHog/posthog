parser grammar HogQLParser;

options {
    tokenVocab = HogQLLexer;
}


program: declaration* EOF;

declaration: varDecl | statement ;

expression: columnExpr;

varDecl: LET identifier ( COLON EQ_SINGLE expression )? ;
identifierList: identifier (COMMA identifier)* COMMA?;

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
varAssignment  : expression COLON EQ_SINGLE expression ;
exprStmt       : expression SEMICOLON?;
emptyStmt      : SEMICOLON ;
block          : LBRACE declaration* RBRACE ;

kvPair: expression ':' expression ;
kvPairList: kvPair (COMMA kvPair)* COMMA?;


// SELECT statement
select: (selectSetStmt | selectStmt | hogqlxTagElement) EOF;

selectStmtWithParens: selectStmt | LPAREN selectSetStmt RPAREN | placeholder;

subsequentSelectSetClause: (EXCEPT | UNION ALL | UNION DISTINCT | INTERSECT | INTERSECT DISTINCT) selectStmtWithParens;
selectSetStmt: selectStmtWithParens (subsequentSelectSetClause)*;

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
    limitByClause?
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
limitByClause: LIMIT limitExpr BY columnExprList;
limitAndOffsetClause
    : LIMIT columnExpr (COMMA columnExpr)? (WITH TIES)? // compact OFFSET-optional form
    | LIMIT columnExpr (WITH TIES)? OFFSET columnExpr // verbose OFFSET-included form with WITH TIES
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
limitExpr: columnExpr ((COMMA | OFFSET) columnExpr)?;
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
    | identifier LPAREN identifier columnTypeExpr (COMMA identifier columnTypeExpr)* COMMA? RPAREN  # ColumnTypeExprNested   // Nested
    | identifier LPAREN enumValue (COMMA enumValue)* COMMA? RPAREN                                  # ColumnTypeExprEnum     // Enum
    | identifier LPAREN columnTypeExpr (COMMA columnTypeExpr)* COMMA? RPAREN                        # ColumnTypeExprComplex  // Array, Tuple
    | identifier LPAREN columnExprList? RPAREN                                               # ColumnTypeExprParam    // FixedString(N)
    ;
columnExprList: columnExpr (COMMA columnExpr)* COMMA?;
columnExpr
    : CASE caseExpr=columnExpr? (WHEN whenExpr=columnExpr THEN thenExpr=columnExpr)+ (ELSE elseExpr=columnExpr)? END          # ColumnExprCase
    | CAST LPAREN columnExpr AS columnTypeExpr RPAREN                                     # ColumnExprCast
    | DATE STRING_LITERAL                                                                 # ColumnExprDate
//    | EXTRACT LPAREN interval FROM columnExpr RPAREN                                      # ColumnExprExtract   // Interferes with a function call
    | INTERVAL STRING_LITERAL                                                             # ColumnExprIntervalString
    | INTERVAL columnExpr interval                                                        # ColumnExprInterval
    | SUBSTRING LPAREN columnExpr FROM columnExpr (FOR columnExpr)? RPAREN                # ColumnExprSubstring
    | TIMESTAMP STRING_LITERAL                                                            # ColumnExprTimestamp
    | TRIM LPAREN (BOTH | LEADING | TRAILING) string FROM columnExpr RPAREN               # ColumnExprTrim
    | identifier (LPAREN columnExprs=columnExprList? RPAREN) (LPAREN DISTINCT? columnArgList=columnExprList? RPAREN)? OVER LPAREN windowExpr RPAREN # ColumnExprWinFunction
    | identifier (LPAREN columnExprs=columnExprList? RPAREN) (LPAREN DISTINCT? columnArgList=columnExprList? RPAREN)? OVER identifier               # ColumnExprWinFunctionTarget
    | identifier (LPAREN columnExprs=columnExprList? RPAREN)? LPAREN DISTINCT? columnArgList=columnExprList? RPAREN                                 # ColumnExprFunction
    | columnExpr LPAREN selectSetStmt RPAREN                                              # ColumnExprCallSelect
    | columnExpr LPAREN columnExprList? RPAREN                                            # ColumnExprCall
    | hogqlxTagElement                                                                    # ColumnExprTagElement
    | templateString                                                                      # ColumnExprTemplateString
    | literal                                                                             # ColumnExprLiteral

    // FIXME(ilezhankin): this part looks very ugly, maybe there is another way to express it
    | columnExpr LBRACKET columnExpr RBRACKET                                             # ColumnExprArrayAccess
    | columnExpr DOT DECIMAL_LITERAL                                                      # ColumnExprTupleAccess
    | columnExpr DOT identifier                                                           # ColumnExprPropertyAccess
    | columnExpr NULL_PROPERTY LBRACKET columnExpr RBRACKET                               # ColumnExprNullArrayAccess
    | columnExpr NULL_PROPERTY DECIMAL_LITERAL                                            # ColumnExprNullTupleAccess
    | columnExpr NULL_PROPERTY identifier                                                 # ColumnExprNullPropertyAccess
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
    | columnExpr (AS identifier | AS STRING_LITERAL)                                      # ColumnExprAlias
    | (tableIdentifier DOT)? ASTERISK                                                     # ColumnExprAsterisk  // single-column only
    | LPAREN selectSetStmt RPAREN                                                         # ColumnExprSubquery  // single-column only
    | LPAREN columnExpr RPAREN                                                            # ColumnExprParens    // single-column only
    | LPAREN columnExprList RPAREN                                                        # ColumnExprTuple
    | LBRACKET columnExprList? RBRACKET                                                   # ColumnExprArray
    | LBRACE (kvPairList)? RBRACE                                                         # ColumnExprDict
    | columnLambdaExpr                                                                    # ColumnExprLambda
    | columnIdentifier                                                                    # ColumnExprIdentifier
    ;

columnLambdaExpr:
    ( LPAREN identifier (COMMA identifier)* COMMA? RPAREN
    |        identifier (COMMA identifier)* COMMA?
    | LPAREN RPAREN
    )
    ARROW (columnExpr | block)
    ;

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
    : identifier AS LPAREN selectSetStmt RPAREN    # WithExprSubquery
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
    | LPAREN selectSetStmt RPAREN      # TableExprSubquery
    | tableExpr (alias | AS identifier)  # TableExprAlias
    | hogqlxTagElement                   # TableExprTag
    | placeholder                        # TableExprPlaceholder
    ;
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
    | CAST | COHORT | COLLATE | CROSS | CUBE | CURRENT | DATE | DESC | DESCENDING
    | DISTINCT | ELSE | END | EXTRACT | FINAL | FIRST
    | FOR | FOLLOWING | FROM | FULL | GROUP | HAVING | ID | IS
    | IF | ILIKE | IN | INNER | INTERVAL | JOIN | KEY
    | LAST | LEADING | LEFT | LIKE | LIMIT
    | NOT | NULLS | OFFSET | ON | OR | ORDER | OUTER | OVER | PARTITION
    | PRECEDING | PREWHERE | RANGE | RETURN | RIGHT | ROLLUP | ROW
    | ROWS | SAMPLE | SELECT | SEMI | SETTINGS | SUBSTRING
    | THEN | TIES | TIMESTAMP | TOTALS | TRAILING | TRIM | TRUNCATE | TO | TOP
    | UNBOUNDED | UNION | USING | WHEN | WHERE | WINDOW | WITH
    ;
keywordForAlias
    : DATE | FIRST | ID | KEY
    ;
alias: IDENTIFIER | keywordForAlias;  // |interval| can't be an alias, otherwise 'INTERVAL 1 SOMETHING' becomes ambiguous.
identifier: IDENTIFIER | interval | keyword;
enumValue: string EQ_SINGLE numberLiteral;
placeholder: LBRACE columnExpr RBRACE;

string: STRING_LITERAL | templateString;
templateString : QUOTE_SINGLE_TEMPLATE stringContents* QUOTE_SINGLE ;
stringContents : STRING_ESCAPE_TRIGGER columnExpr RBRACE | STRING_TEXT;

// These are magic "full template strings", which are used to parse "full text field" templates without the surrounding SQL.
// We will need to add F' to the start of the string to change the lexer's mode.
fullTemplateString: QUOTE_SINGLE_TEMPLATE_FULL stringContentsFull* EOF ;
stringContentsFull : FULL_STRING_ESCAPE_TRIGGER columnExpr RBRACE | FULL_STRING_TEXT;
