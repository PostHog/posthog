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

---

## PostHog-specific functions

These functions are unique to HogQL and not available in standard ClickHouse.

### Visualization

#### `sparkline(array)`

Creates a tiny inline graph from an array of integers. Useful for visualizing trends in table cells.

```sql
-- Basic sparkline
SELECT sparkline(range(1, 10)) FROM (SELECT 1)

-- 24-hour pageview sparkline per URL
SELECT
    pageview,
    sparkline(arrayMap(h -> countEqual(groupArray(hour), h), range(0,23))),
    count() as pageview_count
FROM (
    SELECT
        properties.$current_url as pageview,
        toHour(timestamp) AS hour
    FROM events
    WHERE timestamp > now() - interval 1 day AND event = '$pageview'
) subquery
GROUP BY pageview
ORDER BY pageview_count desc
```

### Version handling

#### `sortableSemVer(version_string)`

Converts a SemVer version number into a sortable format for ordering purposes.

```sql
SELECT DISTINCT properties.$lib_version
FROM events
WHERE event = '$pageview' AND timestamp >= now() - INTERVAL 1 DAY
ORDER BY sortableSemVer(properties.$lib_version) DESC
LIMIT 10
```

### Session replays

#### `recordingButton(session_id)`

Creates a clickable button to view the session replay for a given session ID.

```sql
SELECT
    person.properties.email,
    min_first_timestamp AS start,
    recordingButton(session_id)
FROM raw_session_replay_events
WHERE min_first_timestamp >= now() - INTERVAL 1 DAY
    AND min_first_timestamp <= now()
ORDER BY min_first_timestamp DESC
LIMIT 10
```

### Actions

#### `matchesAction(action_name)`

Filters events that match a named action. Actions are named event combinations defined in PostHog.

```sql
SELECT count()
FROM events
WHERE matchesAction('clicked homepage button')
```

### Localization

#### `languageCodeToName(code)`

Translates a language code (e.g., 'en', 'fr') to its full language name.

```sql
SELECT
    languageCodeToName('en') AS english,  -- English
    languageCodeToName('fr') AS french,   -- French
    languageCodeToName('pt') AS portuguese, -- Portuguese
    languageCodeToName('ru') AS russian,  -- Russian
    languageCodeToName('zh') AS chinese   -- Chinese
```

### HTML rendering

HogQL supports limited HTML tags for rich output in table visualizations. For security, no attributes are supported except for `<a>` tags.

#### Supported tags

- Structure: `<div>`, `<p>`, `<span>`, `<pre>`, `<code>`
- Text formatting: `<em>`, `<strong>`, `<b>`, `<i>`, `<u>`
- Headings: `<h1>`, `<h2>`, `<h3>`, `<h4>`, `<h5>`, `<h6>`
- Lists: `<ul>`, `<ol>`, `<li>`
- Tables: `<table>`, `<thead>`, `<tbody>`, `<tr>`, `<th>`, `<td>`
- Other: `<blockquote>`, `<hr>`

#### Links with `<a>`

Create clickable links. URLs in Table visualization are automatically clickable, but use `<a>` for custom link text.

```sql
SELECT
    properties.$pathname,
    <a href={f'https://posthog.com/{properties.$pathname}'} target='_blank'>Link</a> as link
FROM events
WHERE event = '$pageview'
```

### Text effects

Special tags for visual effects in table output.

#### `<blink>`

Makes text blink.

```sql
SELECT <span>is this <blink>{event}</blink> real?</span> FROM events
```

#### `<marquee>`

Makes text scroll horizontally.

```sql
SELECT <marquee>scrolling text!</marquee> FROM events
```

#### `<redacted>`

Hides text until hovered over.

```sql
SELECT <redacted>hidden until hover</redacted> FROM events
```

#### Combined example

```sql
SELECT
    <span>is this <blink>{event}</blink> real?</span>,
    <marquee>so real, yes!</marquee>,
    <redacted>but this one is hidden</redacted>
FROM events
```
