import { DialectOptions, expandPhrases, formatDialect } from 'sql-formatter'
import { languages } from 'monaco-editor'

const reservedClauses = expandPhrases([
    // queries
    'WITH [RECURSIVE]',
    'FROM',
    'WHERE',
    'GROUP BY [ALL | DISTINCT]',
    'HAVING',
    'WINDOW',
    'PARTITION BY',
    'ORDER BY',
    'LIMIT',
    'OFFSET',
    'FETCH {FIRST | NEXT}',
])

const reservedSetOperations = expandPhrases([
    'UNION [ALL | DISTINCT]',
    'EXCEPT [ALL | DISTINCT]',
    'INTERSECT [ALL | DISTINCT]',
])

const reservedJoins = expandPhrases(['JOIN', '{LEFT | RIGHT | FULL} [OUTER] JOIN', '{INNER | CROSS} JOIN'])

// TODO: these are ripped straight from https://github.com/sql-formatter-org/sql-formatter/blob/9c3feb4bf0bff0cd6ceaa9a487f1aa521e79f7a4/src/languages/sql/sql.keywords.ts not sure what actual datatypes we support!
export const dataTypes: string[] = [
    // https://jakewheat.github.io/sql-overview/sql-2008-foundation-grammar.html#_6_1_data_type
    'ARRAY',
    'BIGINT',
    'BINARY LARGE OBJECT',
    'BINARY VARYING',
    'BINARY',
    'BLOB',
    'BOOLEAN',
    'CHAR LARGE OBJECT',
    'CHAR VARYING',
    'CHAR',
    'CHARACTER LARGE OBJECT',
    'CHARACTER VARYING',
    'CHARACTER',
    'CLOB',
    'DATE',
    'DEC',
    'DECIMAL',
    'DOUBLE',
    'FLOAT',
    'INT',
    'INTEGER',
    'INTERVAL',
    'MULTISET',
    'NATIONAL CHAR VARYING',
    'NATIONAL CHAR',
    'NATIONAL CHARACTER LARGE OBJECT',
    'NATIONAL CHARACTER VARYING',
    'NATIONAL CHARACTER',
    'NCHAR LARGE OBJECT',
    'NCHAR VARYING',
    'NCHAR',
    'NCLOB',
    'NUMERIC',
    'SMALLINT',
    'TIME',
    'TIMESTAMP',
    'VARBINARY',
    'VARCHAR',
]

const createHogQLDialect: (hogQLanguage: languages.IMonarchLanguage) => DialectOptions = (hogQLanguage) => ({
    name: 'hogql',
    tokenizerOptions: {
        reservedSelect: expandPhrases(['SELECT [ALL | DISTINCT]']),
        reservedClauses: [...reservedClauses],
        reservedSetOperations,
        reservedJoins,
        reservedPhrases: [],
        reservedKeywords: hogQLanguage.keywords,
        reservedDataTypes: dataTypes,
        reservedFunctionNames: hogQLanguage.builtinFunctions,
        stringTypes: [
            { quote: "''-qq-bs", prefixes: ['N', 'U&'] },
            { quote: "''-raw", prefixes: ['X'], requirePrefix: true },
        ],
        identTypes: [`""-qq`, '``'],
        paramTypes: { positional: true },
        operators: ['||'],
    },
    formatOptions: {
        onelineClauses: [],
        tabularOnelineClauses: [],
    },
})

export function createHogQLFormattingProvider(language: languages.IMonarchLanguage): languages.DocumentFormattingEditProvider {
    
    const hogQLDialect = createHogQLDialect(language)
    return {
        provideDocumentFormattingEdits(model, options, _token) {
            const currentQuery = model.getValue()

            const formattedQuery = formatDialect(currentQuery, {
                dialect: hogQLDialect,
                tabWidth: options.tabSize,
                useTabs: !options.insertSpaces,
                keywordCase: 'upper',
                paramTypes: {
                    custom: [
                        // Handle `{filters}`, `{cohort_filters}`, etc.
                        { regex: String.raw`\{[a-zA-Z_][a-zA-Z0-9_]*\}` },
                    ],
                },
            })

            if (formattedQuery !== currentQuery) {
                return [
                    {
                        range: model.getFullModelRange(),
                        text: formattedQuery,
                    },
                ]
            }

            return []
        },
    }
}
