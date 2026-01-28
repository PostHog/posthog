# Supported functions

This is an [ever-expanding](https://github.com/posthog/posthog/blob/master/posthog/hogql/constants.py) list of enabled ClickHouse functions.

You can find their full definitions in the [ClickHouse documentation](https://clickhouse.com/docs/en/sql-reference/functions). Additionally, we include a list of popular ones and their uses in the [HogQL expressions](https://posthog.com/docs/hogql/expressions#functions-and-aggregations.md) and [SQL insight](https://posthog.com/docs/product-analytics/sql#useful-functions.md) documentation.

## Type conversion

- `toInt`
- `toFloat`
- `toDecimal`
- `toDate`
- `toDateTime`
- `toUUID`
- `toString`
- `toJSONString`
- `parseDateTime`
- `parseDateTimeBestEffort`

## Arithmetic

- `plus`
- `minus`
- `multiply`
- `divide`
- `intDiv`
- `intDivOrZero`
- `modulo`
- `moduloOrZero`
- `positiveModulo`
- `negate`
- `abs`
- `gcd`
- `lcm`
- `max2`
- `min2`
- `multiplyDecimal`
- `divideDecimal`

## Arrays and strings in common

- `empty`
- `notEmpty`
- `length`
- `reverse`
- `in`
- `notIn`

## Arrays

- `array`
- `range`
- `arrayConcat`
- `arrayElement`
- `has`
- `hasAll`
- `hasAny`
- `hasSubstr`
- `indexOf`
- `arrayCount`
- `countEqual`
- `arrayEnumerate`
- `arrayEnumerateUniq`
- `arrayPopBack`
- `arrayPopFront`
- `arrayPushBack`
- `arrayPushFront`
- `arrayResize`
- `arraySlice`
- `arraySort`
- `arrayReverseSort`
- `arrayUniq`
- `arrayJoin`
- `arrayDifference`
- `arrayDistinct`
- `arrayEnumerateDense`
- `arrayIntersect`
- `arrayReverse`
- `arrayFilter`
- `arrayFlatten`
- `arrayCompact`
- `arrayZip`
- `arrayAUC`
- `arrayMap`
- `arrayFill`
- `arraySplit`
- `arrayReverseFill`
- `arrayReverseSplit`
- `arrayExists`
- `arrayAll`
- `arrayFirst`
- `arrayLast`
- `arrayFirstIndex`
- `arrayLastIndex`
- `arrayMin`
- `arrayMax`
- `arraySum`
- `arrayAvg`
- `arrayCumSum`
- `arrayCumSumNonNegative`
- `arrayProduct`

## Comparison

- `equals`
- `notEquals`
- `less`
- `greater`
- `lessOrEquals`
- `greaterOrEquals`

## Logical

- `and`
- `or`
- `xor`
- `not`

## Type conversions

- `toInt`
- `toFloat`
- `toDecimal`
- `toDate`
- `toDateTime`
- `toUUID`
- `toString`
- `toJSONString`
- `parseDateTime`
- `parseDateTimeBestEffort`

## Dates and times

- `toTimeZone`
- `timeZoneOf`
- `timeZoneOffset`
- `toYear`
- `toQuarter`
- `toMonth`
- `toDayOfYear`
- `toDayOfMonth`
- `toDayOfWeek`
- `toHour`
- `toMinute`
- `toSecond`
- `toUnixTimestamp`
- `toStartOfYear`
- `toStartOfISOYear`
- `toStartOfQuarter`
- `toStartOfMonth`
- `toLastDayOfMonth`
- `toMonday`
- `toStartOfWeek`
- `toStartOfDay`
- `toStartOfHour`
- `toStartOfMinute`
- `toStartOfSecond`
- `toStartOfFiveMinutes`
- `toStartOfTenMinutes`
- `toStartOfFifteenMinutes`
- `toTime`
- `toISOYear`
- `toISOWeek`
- `toWeek`
- `toYearWeek`
- `age`
- `dateDiff`
- `dateTrunc`
- `dateAdd`
- `dateSub`
- `timeStampAdd`
- `timeStampSub`
- `now`
- `NOW`
- `nowInBlock`
- `today`
- `yesterday`
- `timeSlot`
- `toYYYYMM`
- `toYYYYMMDD`
- `toYYYYMMDDhhmmss`
- `addYears`
- `addMonths`
- `addWeeks`
- `addDays`
- `addHours`
- `addMinutes`
- `addSeconds`
- `addQuarters`
- `subtractYears`
- `subtractMonths`
- `subtractWeeks`
- `subtractDays`
- `subtractHours`
- `subtractMinutes`
- `subtractSeconds`
- `subtractQuarters`
- `timeSlots`
- `formatDateTime`
- `dateName`
- `monthName`
- `fromUnixTimestamp`
- `toModifiedJulianDay`
- `fromModifiedJulianDay`
- `toIntervalSecond`
- `toIntervalMinute`
- `toIntervalHour`
- `toIntervalDay`
- `toIntervalWeek`
- `toIntervalMonth`
- `toIntervalQuarter`
- `toIntervalYear`

## Strings

- `lengthUTF8`
- `leftPad`
- `rightPad`
- `leftPadUTF8`
- `rightPadUTF8`
- `lower`
- `upper`
- `lowerUTF8`
- `upperUTF8`
- `isValidUTF8`
- `toValidUTF8`
- `repeat`
- `format`
- `reverseUTF8`
- `concat`
- `substring`
- `substringUTF8`
- `appendTrailingCharIfAbsent`
- `convertCharset`
- `base58Encode`
- `base58Decode`
- `tryBase58Decode`
- `base64Encode`
- `base64Decode`
- `tryBase64Decode`
- `endsWith`
- `startsWith`
- `trim`
- `trimLeft`
- `trimRight`
- `encodeXMLComponent`
- `decodeXMLComponent`
- `extractTextFromHTML`
- `ascii`
- `concatWithSeparator`

## Searching in strings

- `position`
- `positionCaseInsensitive`
- `positionUTF8`
- `positionCaseInsensitiveUTF8`
- `multiSearchAllPositions`
- `multiSearchAllPositionsUTF8`
- `multiSearchFirstPosition`
- `multiSearchFirstIndex`
- `multiSearchAny`
- `match`
- `multiMatchAny`
- `multiMatchAnyIndex`
- `multiMatchAllIndices`
- `multiFuzzyMatchAny`
- `multiFuzzyMatchAnyIndex`
- `multiFuzzyMatchAllIndices`
- `extract`
- `extractAll`
- `extractAllGroupsHorizontal`
- `extractAllGroupsVertical`
- `like`
- `ilike`
- `notLike`
- `notILike`
- `ngramDistance`
- `ngramSearch`
- `countSubstrings`
- `countSubstringsCaseInsensitive`
- `countSubstringsCaseInsensitiveUTF8`
- `countMatches`
- `regexpExtract`

## Replacing in strings

- `replace`
- `replaceAll`
- `replaceOne`
- `replaceRegexpAll`
- `replaceRegexpOne`
- `regexpQuoteMeta`
- `translate`
- `translateUTF8`

## Conditional

- `if`
- `multiIf`

## Mathematical

- `e`
- `pi`
- `exp`
- `log`
- `ln`
- `exp2`
- `log2`
- `exp10`
- `log10`
- `sqrt`
- `cbrt`
- `erf`
- `erfc`
- `lgamma`
- `tgamma`
- `sin`
- `cos`
- `tan`
- `asin`
- `acos`
- `atan`
- `pow`
- `power`
- `intExp2`
- `intExp10`
- `cosh`
- `acosh`
- `sinh`
- `asinh`
- `atanh`
- `atan2`
- `hypot`
- `log1p`
- `sign`
- `degrees`
- `radians`
- `factorial`
- `width_bucket`

## Rounding

- `floor`
- `ceil`
- `trunc`
- `round`
- `roundBankers`
- `roundToExp2`
- `roundDuration`
- `roundAge`
- `roundDown`

## Maps

- `map`
- `mapFromArrays`
- `mapAdd`
- `mapSubtract`
- `mapPopulateSeries`
- `mapContains`
- `mapKeys`
- `mapValues`
- `mapContainsKeyLike`
- `mapExtractKeyLike`
- `mapApply`
- `mapFilter`
- `mapUpdate`

## Splitting strings

- `splitByChar`
- `splitByString`
- `splitByRegexp`
- `splitByWhitespace`
- `splitByNonAlpha`
- `arrayStringConcat`
- `alphaTokens`
- `extractAllGroups`
- `ngrams`
- `tokens`

## Bit

- `bitAnd`
- `bitOr`
- `bitXor`
- `bitNot`
- `bitShiftLeft`
- `bitShiftRight`
- `bitRotateLeft`
- `bitRotateRight`
- `bitSlice`
- `bitTest`
- `bitTestAll`
- `bitTestAny`
- `bitCount`
- `bitHammingDistance`

## Bitmap

- `bitmapBuild`
- `bitmapToArray`
- `bitmapSubsetInRange`
- `bitmapSubsetLimit`
- `subBitmap`
- `bitmapContains`
- `bitmapHasAny`
- `bitmapHasAll`
- `bitmapCardinality`
- `bitmapMin`
- `bitmapMax`
- `bitmapTransform`
- `bitmapAnd`
- `bitmapOr`
- `bitmapXor`
- `bitmapAndnot`
- `bitmapAndCardinality`
- `bitmapOrCardinality`
- `bitmapXorCardinality`
- `bitmapAndnotCardinality`

## URLs

- `protocol`
- `domain`
- `domainWithoutWWW`
- `topLevelDomain`
- `firstSignificantSubdomain`
- `cutToFirstSignificantSubdomain`
- `cutToFirstSignificantSubdomainWithWWW`
- `port`
- `path`
- `pathFull`
- `queryString`
- `fragment`
- `queryStringAndFragment`
- `extractURLParameter`
- `extractURLParameters`
- `extractURLParameterNames`
- `URLHierarchy`
- `URLPathHierarchy`
- `encodeURLComponent`
- `decodeURLComponent`
- `encodeURLFormComponent`
- `decodeURLFormComponent`
- `netloc`
- `cutWWW`
- `cutQueryString`
- `cutFragment`
- `cutQueryStringAndFragment`
- `cutURLParameter`

## JSON

- `isValidJSON`
- `JSONHas`
- `JSONLength`
- `JSONArrayLength`
- `JSONType`
- `JSONExtractUInt`
- `JSONExtractInt`
- `JSONExtractFloat`
- `JSONExtractBool`
- `JSONExtractString`
- `JSONExtractKey`
- `JSONExtractKeys`
- `JSONExtractRaw`
- `JSONExtractArrayRaw`
- `JSONExtractKeysAndValuesRaw`

## Geo

- `greatCircleDistance`
- `geoDistance`
- `greatCircleAngle`
- `pointInEllipses`
- `pointInPolygon`

## Nullable

- `isNull`
- `isNotNull`
- `coalesce`
- `ifNull`
- `nullIf`
- `assumeNotNull`
- `toNullable`

## Tuples

- `tuple`
- `tupleElement`
- `untuple`
- `tupleHammingDistance`
- `tupleToNameValuePairs`
- `tuplePlus`
- `tupleMinus`
- `tupleMultiply`
- `tupleDivide`
- `tupleNegate`
- `tupleMultiplyByNumber`
- `tupleDivideByNumber`
- `dotProduct`

## Time window

- `tumble`
- `hop`
- `tumbleStart`
- `tumbleEnd`
- `hopStart`
- `hopEnd`

## Distance window

- `L1Norm`
- `L2Norm`
- `LinfNorm`
- `LpNorm`
- `L1Distance`
- `L2Distance`
- `LinfDistance`
- `LpDistance`
- `L1Normalize`
- `L2Normalize`
- `LinfNormalize`
- `LpNormalize`
- `cosineDistance`

## Other

- `isFinite`
- `isInfinite`
- `ifNotFinite`
- `isNaN`
- `bar`
- `transform`
- `formatReadableDecimalSize`
- `formatReadableSize`
- `formatReadableQuantity`
- `formatReadableTimeDelta`
