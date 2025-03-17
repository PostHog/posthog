// Adapted from https://raw.githubusercontent.com/microsoft/monaco-editor/main/src/basic-languages/mysql/mysql.ts

import { Monaco } from '@monaco-editor/react'
import { hogQLAutocompleteProvider } from 'lib/monaco/hogQLAutocompleteProvider'
import { hogQLMetadataProvider } from 'lib/monaco/hogQLMetadataProvider'
import { languages } from 'monaco-editor'

import { HogLanguage } from '~/queries/schema/schema-general'

export const conf: () => languages.LanguageConfiguration = () => ({
    comments: {
        lineComment: '--',
        blockComment: ['/*', '*/'],
    },
    brackets: [
        ['{', '}'],
        ['[', ']'],
        ['(', ')'],
    ],
    autoClosingPairs: [
        { open: '{', close: '}' },
        { open: '[', close: ']' },
        { open: '(', close: ')' },
        { open: '"', close: '"' },
        { open: "'", close: "'" },
    ],
    surroundingPairs: [
        { open: '{', close: '}' },
        { open: '[', close: ']' },
        { open: '(', close: ')' },
        { open: '"', close: '"' },
        { open: "'", close: "'" },
    ],
})

export const language: () => languages.IMonarchLanguage = () => ({
    defaultToken: '',
    tokenPostfix: '.sql',
    ignoreCase: true,

    brackets: [
        { open: '[', close: ']', token: 'delimiter.square' },
        { open: '(', close: ')', token: 'delimiter.parenthesis' },
    ],

    keywords: [
        'ALL',
        'ANTI',
        'ANY',
        'ARRAY',
        'AS',
        'ASCENDING',
        'ASOF',
        'BOTH',
        'BY',
        'CASE',
        'CAST',
        'COHORT',
        'COLLATE',
        'CROSS',
        'CUBE',
        'CURRENT',
        'DATE',
        'DAY',
        'DESC',
        'DESCENDING',
        'DISTINCT',
        'ELSE',
        'END',
        'EXTRACT',
        'FINAL',
        'FIRST',
        'FN',
        'FOLLOWING',
        'FOR',
        'FROM',
        'FULL',
        'GROUP',
        'HAVING',
        'HOUR',
        'ID',
        'IF',
        'INF',
        'INTERVAL',
        'KEY',
        'LAST',
        'LEADING',
        'LET',
        'LIMIT',
        'MINUTE',
        'MONTH',
        'NAN_SQL',
        'NULL_SQL',
        'NULLS',
        'OFFSET',
        'ON',
        'ORDER',
        'OVER',
        'PARTITION',
        'PRECEDING',
        'PREWHERE',
        'QUARTER',
        'RANGE',
        'RETURN',
        'ROLLUP',
        'ROW',
        'ROWS',
        'SAMPLE',
        'SECOND',
        'SELECT',
        'SEMI',
        'SETTINGS',
        'SUBSTRING',
        'THEN',
        'TIES',
        'TO',
        'TOP',
        'TOTALS',
        'TRAILING',
        'TRIM',
        'TRUNCATE',
        'UNBOUNDED',
        'USING',
        'WEEK',
        'WHEN',
        'WHERE',
        'WHILE',
        'WINDOW',
        'WITH',
        'YEAR',
    ],
    operators: [
        'AND',
        'BETWEEN',
        'IN',
        'LIKE',
        'ILIKE',
        'NOT',
        'OR',
        'IS',
        'NULL',
        'UNION',
        'INNER',
        'JOIN',
        'LEFT',
        'OUTER',
        'RIGHT',
    ],
    builtinFunctions: [
        'plus',
        'minus',
        'multiply',
        'divide',
        'intDiv',
        'intDivOrZero',
        'modulo',
        'moduloOrZero',
        'positiveModulo',
        'negate',
        'abs',
        'gcd',
        'lcm',
        'max2',
        'min2',
        'multiplyDecimal',
        'divideDecimal',
        'empty',
        'notEmpty',
        'length',
        'reverse',
        'array',
        'range',
        'arrayConcat',
        'arrayElement',
        'has',
        'hasAll',
        'hasAny',
        'hasSubstr',
        'indexOf',
        'arrayCount',
        'countEqual',
        'arrayEnumerate',
        'arrayEnumerateUniq',
        'arrayPopBack',
        'arrayPopFront',
        'arrayPushBack',
        'arrayPushFront',
        'arrayResize',
        'arraySlice',
        'arraySort',
        'arrayReverseSort',
        'arrayUniq',
        'arrayJoin',
        'arrayDifference',
        'arrayDistinct',
        'arrayEnumerateDense',
        'arrayIntersect',
        'arrayReverse',
        'arrayFilter',
        'arrayFlatten',
        'arrayCompact',
        'arrayZip',
        'arrayAUC',
        'arrayMap',
        'arrayFill',
        'arraySplit',
        'arrayReverseFill',
        'arrayReverseSplit',
        'arrayExists',
        'arrayAll',
        'arrayFirst',
        'arrayLast',
        'arrayFirstIndex',
        'arrayLastIndex',
        'arrayMin',
        'arrayMax',
        'arraySum',
        'arrayAvg',
        'arrayCumSum',
        'arrayCumSumNonNegative',
        'arrayProduct',
        'equals',
        'notEquals',
        'less',
        'greater',
        'lessOrEquals',
        'greaterOrEquals',
        'and',
        'or',
        'xor',
        'not',
        'hex',
        'unhex',
        'reinterpretAsUInt8',
        'reinterpretAsUInt16',
        'reinterpretAsUInt32',
        'reinterpretAsUInt64',
        'reinterpretAsUInt128',
        'reinterpretAsUInt256',
        'reinterpretAsInt8',
        'reinterpretAsInt16',
        'reinterpretAsInt32',
        'reinterpretAsInt64',
        'reinterpretAsInt128',
        'reinterpretAsInt256',
        'reinterpretAsFloat32',
        'reinterpretAsFloat64',
        'toInt',
        '_toInt64',
        'toFloat',
        'toDecimal',
        '_toDate',
        'toDate',
        'toDateTime',
        'toUUID',
        'toString',
        'toJSONString',
        'parseDateTime',
        'parseDateTimeBestEffort',
        'toTypeName',
        'toTimeZone',
        'timeZoneOf',
        'timeZoneOffset',
        'toYear',
        'toQuarter',
        'toMonth',
        'toDayOfYear',
        'toDayOfMonth',
        'toDayOfWeek',
        'toHour',
        'toMinute',
        'toSecond',
        'toUnixTimestamp',
        'toUnixTimestamp64Milli',
        'toStartOfYear',
        'toStartOfISOYear',
        'toStartOfQuarter',
        'toStartOfMonth',
        'toLastDayOfMonth',
        'toMonday',
        'toStartOfWeek',
        'toStartOfDay',
        'toLastDayOfWeek',
        'toStartOfHour',
        'toStartOfMinute',
        'toStartOfSecond',
        'toStartOfFiveMinutes',
        'toStartOfTenMinutes',
        'toStartOfFifteenMinutes',
        'toTime',
        'toISOYear',
        'toISOWeek',
        'toWeek',
        'toYearWeek',
        'age',
        'dateDiff',
        'dateTrunc',
        'dateAdd',
        'dateSub',
        'timeStampAdd',
        'timeStampSub',
        'now',
        'nowInBlock',
        'rowNumberInAllBlocks',
        'today',
        'yesterday',
        'timeSlot',
        'toYYYYMM',
        'toYYYYMMDD',
        'toYYYYMMDDhhmmss',
        'addYears',
        'addMonths',
        'addWeeks',
        'addDays',
        'addHours',
        'addMinutes',
        'addSeconds',
        'addQuarters',
        'subtractYears',
        'subtractMonths',
        'subtractWeeks',
        'subtractDays',
        'subtractHours',
        'subtractMinutes',
        'subtractSeconds',
        'subtractQuarters',
        'timeSlots',
        'formatDateTime',
        'dateName',
        'monthName',
        'fromUnixTimestamp',
        'toModifiedJulianDay',
        'fromModifiedJulianDay',
        'toIntervalSecond',
        'toIntervalMinute',
        'toIntervalHour',
        'toIntervalDay',
        'toIntervalWeek',
        'toIntervalMonth',
        'toIntervalQuarter',
        'toIntervalYear',
        'left',
        'right',
        'lengthUTF8',
        'leftPad',
        'rightPad',
        'leftPadUTF8',
        'rightPadUTF8',
        'lower',
        'upper',
        'lowerUTF8',
        'upperUTF8',
        'isValidUTF8',
        'toValidUTF8',
        'repeat',
        'format',
        'reverseUTF8',
        'concat',
        'substring',
        'substringUTF8',
        'appendTrailingCharIfAbsent',
        'convertCharset',
        'base58Encode',
        'base58Decode',
        'tryBase58Decode',
        'base64Encode',
        'base64Decode',
        'tryBase64Decode',
        'endsWith',
        'startsWith',
        'trim',
        'trimLeft',
        'trimRight',
        'encodeXMLComponent',
        'decodeXMLComponent',
        'extractTextFromHTML',
        'ascii',
        'concatWithSeparator',
        'position',
        'positionCaseInsensitive',
        'positionUTF8',
        'positionCaseInsensitiveUTF8',
        'multiSearchAllPositions',
        'multiSearchAllPositionsUTF8',
        'multiSearchFirstPosition',
        'multiSearchFirstIndex',
        'multiSearchAny',
        'match',
        'multiMatchAny',
        'multiMatchAnyIndex',
        'multiMatchAllIndices',
        'multiFuzzyMatchAny',
        'multiFuzzyMatchAnyIndex',
        'multiFuzzyMatchAllIndices',
        'extract',
        'extractAll',
        'extractAllGroupsHorizontal',
        'extractAllGroupsVertical',
        'like',
        'ilike',
        'notLike',
        'notILike',
        'ngramDistance',
        'ngramSearch',
        'countSubstrings',
        'countSubstringsCaseInsensitive',
        'countSubstringsCaseInsensitiveUTF8',
        'countMatches',
        'regexpExtract',
        'replace',
        'replaceAll',
        'replaceOne',
        'replaceRegexpAll',
        'replaceRegexpOne',
        'regexpQuoteMeta',
        'translate',
        'translateUTF8',
        'if',
        'multiIf',
        'e',
        'pi',
        'exp',
        'log',
        'ln',
        'exp2',
        'log2',
        'exp10',
        'log10',
        'sqrt',
        'cbrt',
        'erf',
        'erfc',
        'lgamma',
        'tgamma',
        'sin',
        'cos',
        'tan',
        'asin',
        'acos',
        'atan',
        'pow',
        'power',
        'intExp2',
        'intExp10',
        'cosh',
        'acosh',
        'sinh',
        'asinh',
        'atanh',
        'atan2',
        'hypot',
        'log1p',
        'sign',
        'degrees',
        'radians',
        'factorial',
        'width_bucket',
        'floor',
        'ceil',
        'trunc',
        'round',
        'roundBankers',
        'roundToExp2',
        'roundDuration',
        'roundAge',
        'roundDown',
        'map',
        'mapFromArrays',
        'mapAdd',
        'mapSubtract',
        'mapPopulateSeries',
        'mapContains',
        'mapKeys',
        'mapValues',
        'mapContainsKeyLike',
        'mapExtractKeyLike',
        'mapApply',
        'mapFilter',
        'mapUpdate',
        'splitByChar',
        'splitByString',
        'splitByRegexp',
        'splitByWhitespace',
        'splitByNonAlpha',
        'arrayStringConcat',
        'alphaTokens',
        'extractAllGroups',
        'ngrams',
        'tokens',
        'bitAnd',
        'bitOr',
        'bitXor',
        'bitNot',
        'bitShiftLeft',
        'bitShiftRight',
        'bitRotateLeft',
        'bitRotateRight',
        'bitSlice',
        'bitTest',
        'bitTestAll',
        'bitTestAny',
        'bitCount',
        'bitHammingDistance',
        'bitmapBuild',
        'bitmapToArray',
        'bitmapSubsetInRange',
        'bitmapSubsetLimit',
        'subBitmap',
        'bitmapContains',
        'bitmapHasAny',
        'bitmapHasAll',
        'bitmapCardinality',
        'bitmapMin',
        'bitmapMax',
        'bitmapTransform',
        'bitmapAnd',
        'bitmapOr',
        'bitmapXor',
        'bitmapAndnot',
        'bitmapAndCardinality',
        'bitmapOrCardinality',
        'bitmapXorCardinality',
        'bitmapAndnotCardinality',
        'protocol',
        'domain',
        'domainWithoutWWW',
        'topLevelDomain',
        'firstSignificantSubdomain',
        'cutToFirstSignificantSubdomain',
        'cutToFirstSignificantSubdomainWithWWW',
        'port',
        'path',
        'pathFull',
        'queryString',
        'fragment',
        'queryStringAndFragment',
        'extractURLParameter',
        'extractURLParameters',
        'extractURLParameterNames',
        'URLHierarchy',
        'URLPathHierarchy',
        'encodeURLComponent',
        'decodeURLComponent',
        'encodeURLFormComponent',
        'decodeURLFormComponent',
        'netloc',
        'cutWWW',
        'cutQueryString',
        'cutFragment',
        'cutQueryStringAndFragment',
        'cutURLParameter',
        'isValidJSON',
        'JSONHas',
        'JSONLength',
        'JSONArrayLength',
        'JSONType',
        'JSONExtractUInt',
        'JSONExtractInt',
        'JSONExtractFloat',
        'JSONExtractBool',
        'JSONExtractString',
        'JSONExtractKey',
        'JSONExtractKeys',
        'JSONExtractRaw',
        'JSONExtractArrayRaw',
        'JSONExtractKeysAndValues',
        'JSONExtractKeysAndValuesRaw',
        'JSON_VALUE',
        'in',
        'notIn',
        'greatCircleDistance',
        'geoDistance',
        'greatCircleAngle',
        'pointInEllipses',
        'pointInPolygon',
        'geohashEncode',
        'geohashDecode',
        'geohashesInBox',
        'isnull',
        'isNotNull',
        'coalesce',
        'ifnull',
        'nullif',
        'assumeNotNull',
        'toNullable',
        'tuple',
        'tupleElement',
        'untuple',
        'tupleHammingDistance',
        'tupleToNameValuePairs',
        'tuplePlus',
        'tupleMinus',
        'tupleMultiply',
        'tupleDivide',
        'tupleNegate',
        'tupleMultiplyByNumber',
        'tupleDivideByNumber',
        'dotProduct',
        'isFinite',
        'isInfinite',
        'ifNotFinite',
        'isNaN',
        'bar',
        'transform',
        'formatReadableDecimalSize',
        'formatReadableSize',
        'formatReadableQuantity',
        'formatReadableTimeDelta',
        'least',
        'greatest',
        'tumble',
        'hop',
        'tumbleStart',
        'tumbleEnd',
        'hopStart',
        'hopEnd',
        'L1Norm',
        'L2Norm',
        'LinfNorm',
        'LpNorm',
        'L1Distance',
        'L2Distance',
        'LinfDistance',
        'LpDistance',
        'L1Normalize',
        'L2Normalize',
        'LinfNormalize',
        'LpNormalize',
        'cosineDistance',
        'rank',
        'dense_rank',
        'row_number',
        'first_value',
        'last_value',
        'nth_value',
        'lagInFrame',
        'leadInFrame',
        'equals',
        'notEquals',
        'less',
        'greater',
        'lessOrEquals',
        'greaterOrEquals',
        'like',
        'ilike',
        'notLike',
        'notILike',
        'in',
        'notIn',
        'count',
        'countIf',
        'countDistinctIf',
        'min',
        'minIf',
        'max',
        'maxIf',
        'sum',
        'sumIf',
        'avg',
        'avgIf',
        'any',
        'anyIf',
        'stddevPop',
        'stddevPopIf',
        'stddevSamp',
        'stddevSampIf',
        'varPop',
        'varPopIf',
        'varSamp',
        'varSampIf',
        'covarPop',
        'covarPopIf',
        'covarSamp',
        'covarSampIf',
        'corr',
        'anyHeavy',
        'anyHeavyIf',
        'anyLast',
        'anyLastIf',
        'argMin',
        'argMinIf',
        'argMax',
        'argMaxIf',
        'argMinMerge',
        'argMaxMerge',
        'avgState',
        'avgMerge',
        'avgWeighted',
        'avgWeightedIf',
        'avgArray',
        'groupArray',
        'groupUniqArray',
        'groupUniqArrayIf',
        'groupArrayInsertAt',
        'groupArrayInsertAtIf',
        'groupArrayMovingAvg',
        'groupArrayMovingAvgIf',
        'groupArrayMovingSum',
        'groupArrayMovingSumIf',
        'groupBitAnd',
        'groupBitAndIf',
        'groupBitOr',
        'groupBitOrIf',
        'groupBitXor',
        'groupBitXorIf',
        'groupBitmap',
        'groupBitmapIf',
        'groupBitmapAnd',
        'groupBitmapAndIf',
        'groupBitmapOr',
        'groupBitmapOrIf',
        'groupBitmapXor',
        'groupBitmapXorIf',
        'sumWithOverflow',
        'sumWithOverflowIf',
        'deltaSum',
        'deltaSumIf',
        'deltaSumTimestamp',
        'deltaSumTimestampIf',
        'sumMap',
        'sumMapIf',
        'sumMapMerge',
        'minMap',
        'minMapIf',
        'maxMap',
        'maxMapIf',
        'medianArray',
        'skewSamp',
        'skewSampIf',
        'skewPop',
        'skewPopIf',
        'kurtSamp',
        'kurtSampIf',
        'kurtPop',
        'kurtPopIf',
        'uniq',
        'uniqIf',
        'uniqExact',
        'uniqExactIf',
        'uniqHLL12',
        'uniqHLL12If',
        'uniqTheta',
        'uniqThetaIf',
        'median',
        'medianIf',
        'medianExact',
        'medianExactIf',
        'medianExactLow',
        'medianExactLowIf',
        'medianExactHigh',
        'medianExactHighIf',
        'medianExactWeighted',
        'medianExactWeightedIf',
        'medianTiming',
        'medianTimingIf',
        'medianTimingWeighted',
        'medianTimingWeightedIf',
        'medianDeterministic',
        'medianDeterministicIf',
        'medianTDigest',
        'medianTDigestIf',
        'medianTDigestWeighted',
        'medianTDigestWeightedIf',
        'medianBFloat16',
        'medianBFloat16If',
        'quantile',
        'quantileIf',
        'quantiles',
        'quantilesIf',
        'simpleLinearRegression',
        'simpleLinearRegressionIf',
        'contingency',
        'contingencyIf',
        'cramersV',
        'cramersVIf',
        'cramersVBiasCorrected',
        'cramersVBiasCorrectedIf',
        'theilsU',
        'theilsUIf',
        'maxIntersections',
        'maxIntersectionsIf',
        'maxIntersectionsPosition',
        'maxIntersectionsPositionIf',
    ],
    builtinVariables: [],
    tokenizer: {
        root: [
            { include: '@comments' },
            { include: '@whitespace' },
            { include: '@numbers' },
            { include: '@strings' },
            { include: '@complexIdentifiers' },
            { include: '@scopes' },
            [/[;,.]/, 'delimiter'],
            [/[()]/, '@brackets'],
            [
                /[\w@]+/,
                {
                    cases: {
                        '@operators': 'operator',
                        '@builtinVariables': 'predefined',
                        '@builtinFunctions': 'predefined',
                        '@keywords': 'keyword',
                        '@default': 'identifier',
                    },
                },
            ],
            [/[<>=!%&+\-*/|~^]/, 'operator'],
        ],
        whitespace: [[/\s+/, 'white']],
        comments: [
            [/--+.*/, 'comment'],
            [/#+.*/, 'comment'],
            [/\/\*/, { token: 'comment.quote', next: '@comment' }],
        ],
        comment: [
            [/[^*/]+/, 'comment'],
            // Not supporting nested comments, as nested comments seem to not be standard?
            // i.e. http://stackoverflow.com/questions/728172/are-there-multiline-comment-delimiters-in-sql-that-are-vendor-agnostic
            // [/\/\*/, { token: 'comment.quote', next: '@push' }],    // nested comment not allowed :-(
            [/\*\//, { token: 'comment.quote', next: '@pop' }],
            [/./, 'comment'],
        ],
        numbers: [
            [/0[xX][0-9a-fA-F]*/, 'number'],
            [/[$][+-]*\d*(\.\d*)?/, 'number'],
            [/((\d+(\.\d*)?)|(\.\d+))([eE][-+]?\d+)?/, 'number'],
        ],
        strings: [
            [/'/, { token: 'string', next: '@string' }],
            [/"/, { token: 'string.double', next: '@stringDouble' }],
        ],
        string: [
            [/\\'/, 'string'],
            [/[^']+/, 'string'],
            [/''/, 'string'],
            [/'/, { token: 'string', next: '@pop' }],
        ],
        stringDouble: [
            [/[^"]+/, 'string.double'],
            [/""/, 'string.double'],
            [/"/, { token: 'string.double', next: '@pop' }],
        ],
        complexIdentifiers: [[/`/, { token: 'identifier.quote', next: '@quotedIdentifier' }]],
        quotedIdentifier: [
            [/[^`]+/, 'identifier'],
            [/``/, 'identifier'],
            [/`/, { token: 'identifier.quote', next: '@pop' }],
        ],
        scopes: [
            // NOT SUPPORTED
        ],
    },
})

export function initHogQLLanguage(monaco: Monaco, lang: HogLanguage = HogLanguage.hogQL): void {
    if (!monaco.languages.getLanguages().some(({ id }) => id === lang)) {
        monaco.languages.register(
            lang === 'hogQL'
                ? {
                      id: lang,
                      extensions: ['.sql', '.hogql'],
                      mimetypes: ['application/hogql'],
                  }
                : {
                      id: lang,
                      mimetypes: ['application/hogql+expr'],
                  }
        )
        monaco.languages.setLanguageConfiguration(lang, conf())
        monaco.languages.setMonarchTokensProvider(lang, language())
        monaco.languages.registerCompletionItemProvider(lang, hogQLAutocompleteProvider(lang))
        monaco.languages.registerCodeActionProvider(lang, hogQLMetadataProvider())
    }
}
