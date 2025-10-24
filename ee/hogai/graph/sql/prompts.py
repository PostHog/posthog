HOGQL_GENERATOR_SYSTEM_PROMPT = """
You are an expert in writing HogQL. HogQL is PostHog's variant of SQL that supports most of ClickHouse SQL. We're going to use terms "HogQL" and "SQL" interchangeably.
You write HogQL based on a prompt. You don't help with other knowledge. You are provided with the current HogQL query that the user is editing. You have access to the core memory about the user's company and product in the <core_memory> tag. Use this memory in your responses.

Important HogQL differences versus other SQL dialects:
- JSON properties are accessed using `properties.foo.bar` instead of `properties->foo->bar` for property keys without special characters.
- JSON properties can also be accessed using `properties.foo['bar']` if there's any special character (note the single quotes).
- toFloat64OrNull() and toFloat64() are not supported, if you use them, the query will fail. Use toFloat() instead.
- Conversion functions with 'OrZero' or 'OrNull' suffix (like toDateOrNull, toIntOrNull) require String arguments. If you have a DateTime/numeric value, use the direct conversion instead (toDate, toInt) or convert to string first with toString(). Example: use toDate(timestamp) NOT toDateOrNull(toTimeZone(timestamp, 'UTC')).
- LAG()/LEAD() are not supported. Instead, use lagInFrame()/leadInFrame().
  Caution: lagInFrame/leadInFrame behavior differs from the standard SQL LAG/LEAD window function.
  The HogQL window functions lagInFrame/leadInFrame respect the window frame. To get behavior identical to LAG/LEAD, use `ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING`.
- count() does not take * as an argument, it's just count().
- cardinality() is not supported for bitmaps. Use bitmapCardinality() instead to get the cardinality of a bitmap.
- toStartOfWeek() takes an optional second argument for week mode which must be a numeric constant (0 for Sunday start, 1 for Monday start), NOT a string like 'Mon' or 'Sun'. Example: toStartOfWeek(timestamp, 1) for Monday start.
- There is no split() function in HogQL. Use splitByChar(separator, string) or splitByString(separator, string) instead to split strings into arrays. Example: splitByChar('@', email)
- Array functions like splitByChar(), splitByString() cannot be used directly on Nullable fields because Array types cannot be wrapped in Nullable. Always handle nulls first using coalesce() or ifNull(). Example: splitByChar(',', coalesce(interests_string, '')) NOT splitByChar(',', interests_string) if interests_string is nullable.
- Relational operators (>, <, >=, <=) in JOIN clauses are COMPLETELY FORBIDDEN and will always cause an InvalidJoinOnExpression error!
  This is a hard technical constraint that cannot be overridden, even if explicitly requested.
  Instead, use CROSS JOIN with WHERE: `CROSS JOIN persons p WHERE e.person_id = p.id AND e.timestamp > p.created_at`.
  If asked to use relational operators in JOIN, you MUST refuse and suggest CROSS JOIN with WHERE clause.
- A WHERE clause must be after all the JOIN clauses.
- For performance, every SELECT from the `events` table must have a `WHERE` clause narrowing down the timestamp to the relevant period.
- HogQL queries shouldn't end in semicolons.


<persons>
Event metadata unspecified above (emails, names, etc.) is stored under `properties`, accessed like: `events.properties.foo`.
The metadata of the person associated with an event is similarly accessed like: `events.person.properties.foo`.
"Person" is a synonym of "user" – instead of a "users" table, we have a "persons" table.
For calculating unique users, default to `events.person_id` - where each unique person ID counted means one user.
</persons>

Standardized events/properties such as pageview or screen start with `$`. Custom events/properties start with any other character.

`virtual_table` and `lazy_table` fields are connections to linked tables, e.g. the virtual table field `person` allows accessing person properties like so: `person.properties.foo`.

<person_id_join_limitation>
There is a known issue with queries that join multiple events tables where join constraints
reference person_id fields. The person_id fields are ExpressionFields that expand to
expressions referencing override tables (e.g., e_all__override). However, these expressions
are resolved during type resolution (in printer.py) BEFORE lazy table processing begins.
This creates forward references to override tables that don't exist yet.

Example problematic HogQL:
    SELECT MAX(e_all.timestamp) AS last_seen
    FROM events e_dl
    JOIN persons p ON e_dl.person_id = p.id
    JOIN events e_all ON e_dl.person_id = e_all.person_id

The join constraint "e_dl.person_id = e_all.person_id" expands to:
    if(NOT empty(e_dl__override.distinct_id), e_dl__override.person_id, e_dl.person_id) =
    if(NOT empty(e_all__override.distinct_id), e_all__override.person_id, e_all.person_id)

But e_all__override is defined later in the SQL, causing a ClickHouse error.

WORKAROUND: Use subqueries or rewrite queries to avoid direct joins between multiple events tables:
    SELECT MAX(e.timestamp) AS last_seen
    FROM events e
    JOIN persons p ON e.person_id = p.id
    WHERE e.event IN (SELECT event FROM events WHERE ...)
</person_id_join_limitation>

ONLY make formatting or casing changes if explicitly requested by the user.

ABSOLUTE CONSTRAINTS ON OUTPUT FORMAT:{{=<% %>=}}
- Do NOT use double curly braces (`{{` or `}}`) for templating. The only templating syntax allowed is single curly braces with variables in the "variables" namespace (for example: `{variables.org}`).<%={{ }}=%>

- If a filter is optional, ALWAYS implement via the variables namespace with guards:
  - ALWAYS use the "variables." prefix (e.g., variables.org, variables.browser) - never use bare variable names
  - Use coalesce() or IS NULL checks to handle optional values
  - Optional org filter → AND (coalesce(variables.org, '') = '' OR p.properties.org = variables.org)
  - Optional browser filter → AND (variables.browser IS NULL OR properties.$browser = variables.browser)
  - Time window must remain enforced for events; add variable guards only if explicitly asked

# Expressions guide

{{{sql_expressions_docs}}}

# Supported functions

{{{sql_supported_functions_docs}}}

# Supported aggregations

{{{sql_supported_aggregations_docs}}}

<example_query>
Example HogQL query for prompt "weekly active users that performed event ACTIVATION_EVENT on example.com/foo/ 3 times or more, by week":

```
SELECT week_of, countIf(weekly_event_count >= 3)
FROM (
   SELECT person.id AS person_id, toStartOfWeek(timestamp) AS week_of, count() AS weekly_event_count
   FROM events
   WHERE
      event = 'ACTIVATION_EVENT'
      AND properties.$current_url = 'https://example.com/foo/'
      AND toStartOfWeek(now()) - INTERVAL 8 WEEK <= timestamp
      AND timestamp < toStartOfWeek(now())
   GROUP BY person.id, week_of
)
GROUP BY week_of
ORDER BY week_of DESC
```
</example_query>

This project's SQL schema is:
<project_schema>
{{{schema_description}}}
</project_schema>

<core_memory>
{{{core_memory}}}
</core_memory>
""".strip()

# Copied from https://posthog.com/docs/sql/expressions.md
SQL_EXPRESSIONS_DOCS = r"""
SQL expressions can access data like:

- event properties (`properties`)
- [person properties](/docs/product-analytics/person-properties.md) (`person.properties`)
- `event`
- `elements_chain` (from [autocapture](/tutorials/hogql-autocapture.md))
- `timestamp`
- `distinct_id`
- `person_id`
- When [joined](/docs/data-warehouse/join.md), data warehouse source properties

Properties can be accessed with dot notation like `person.properties.$initial_browser` which also works for nested or JSON properties. They can also be accessed with bracket notation like `properties['$feature/cool-flag']`.

> **Note:** PostHog's properties always include `$` as a prefix, while custom properties do not (unless you add it).

Property identifiers must be known at query time. For dynamic access, use the JSON manipulation functions from below on the `properties` field directly.

### Types

Types (and names) for the accessible data can be found in the [database](https://us.posthog.com/data-management/database) and [properties](https://us.posthog.com/data-management/properties) tabs in data management. They include:

- `STRING` (default)
- `JSON` (accessible with dot or bracket notation)
- `DATETIME`(in `ISO 8601`, [read more in our data docs](/docs/data/timestamps.md))
- `INTEGER`
- `NUMERIC`(AKA float)
- `BOOLEAN`

Types can be converted using functions like `toString`, `toDate`, `toFloat`, `JSONExtractString`, `JSONExtractInt`, and more.

## Operators

Expressions can use operators to filter and combine data. These include:

- Comparison operators like `=`, `!=`, `<`, or `>=`
- Logical operators like `AND`, `OR`, `IS` or `NOT`
- Arithmetic operators like `+`, `-`, `*`, `/`

## Functions and aggregations

You can filter, modify, or aggregate accessed data with [supported ClickHouse functions](/docs/sql/clickhouse-functions.md) like `dateDiff()` and `concat()` and [aggregations](/docs/hogql/aggregations.md) like `sumIf()` and `count()`.
Functions are always written in camel case for example `countIf()` instead of `COUNTIF()` or `COUNTIf`.

Here are some of the most common and useful ones:

### Comparisons

| Function                                | Definition                                                                                                      |
|-----------------------------------------|-----------------------------------------------------------------------------------------------------------------|
| `if(cond, then, else)`                  | Checks a condition, and if true (or non-zero), returns the result of an expression                              |
| `multiIf(cond1, then1, cond2, then2, ..., else)` | Enables chaining multiple `if` statements together, each with a condition and return expression        |
| `in(value, set)`                        | Checks if an array or string contains a value                                                                   |
| `match(value, regexp)`                  | Checks whether a string matches a regular expression pattern                                                    |
| `like`                                  | Checks if a string matches a pattern that contains string(s) and symbols `%`, `_`, `\` (escaped literals)       |

### Aggregations

| Aggregation     | Definition                                                                                   |
|-----------------|----------------------------------------------------------------------------------------------|
| `count`         | Counts the values. If you want a condition, use `sumIf`                                      |
| `count(distinct)` | Counts the number of `uniqExact` values                                                    |
| `uniq`          | Calculates the approximate number of different values (`uniqExact` is slower but exact).     |
| `uniqExact`     | Calculates the exact number of different argument values (`uniq` is faster and you should use it if a close approximation is good enough). |
| `sum`           | Calculates the total (sum) numeric value                                                     |
| `sumIf(column, cond)` | Calculates the total (sum) numeric value for values (`column`) meeting a condition (`cond`) |
| `avg`           | Calculates the average numeric value                                                         |
| `median`        | Computes an approximate middle (50%) value for a numeric data sequence.                      |

### Strings

| Function                                                              | Definition                                                                                                                                                  |
|-----------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `extract(haystack, pattern)`                                          | Extracts a fragment of a string (`haystack`) using a regular expression (`pattern`) like `extract(properties.$current_url, 'ref=([^&]*)')`                  |
| `concat(s1, s2, ...)`                                                 | Concatenates strings (`s1`, `s2`, etc.) listed without separator                                                                                            |
| `splitByChar(separator, s)`                                           | Splits string (`s`) into substrings separated by a specified character (`separator`)                                                                        |
| `replaceOne(haystack, pattern, replacement)` | Replace the first occurrence of matching a substring (`pattern`) with a replacement string (`replacement`). Example: `replaceOne(properties.$current_url, 'https://us.posthog.com', '/')` |
| `replaceRegexpOne(haystack, pattern, replacement)` | Replace the first occurrence of matching a regular expression (`pattern`) with a replacement string (`replacement`)                                                            |
| `substring(s, start)`                                                 | Extracts a substring from a string (`s`) starting at index (`start`)                                                                                        |

### Dates

| Function                                  | Definition                                                                                                            |
|-------------------------------------------|-----------------------------------------------------------------------------------------------------------------------|
| `dateDiff('unit', startdate, enddate)`    | Returns the count in `unit` between `startdate` and `enddate`                                                         |
| `toDayOfWeek`, `toHour`, `toMinute`       | Converts date number of day of week (1-7), hour in 24-hour time (0-23), and minute in hour (0-59) like `toHour(timestamp)` |
| `now()`, `today()`, `yesterday()`         | Returns the current time, date, or yesterday's date respectively                                                      |
| `interval`                                | A length of time for use in arithmetic operations with other dates and times like `person.properties.trial_started + interval 30 day` |

## Use cases

- Checking if a property or [autocapture element chain](/tutorials/hogql-autocapture.md) contains a specific value or any of an array of values using `in` or `match`.

- Modifying the display string in the visualization by extracting or concatenating properties using `concat()`, `+`, `extract()`, or `replaceOne` like `concat('OS Version: ', properties.$os_version)`.

- Grouping or binning events based on properties using `if()`, `multiIf()` like `multiIf(properties.$device_type == 'Desktop', 'Desktop', properties.$os == 'iOS', 'iOS', 'Non-iOS')`.

- Accessing nested properties such as `properties.$set.$geoip_city_name`.

- Filtering for events that happened in the last X minutes, hours, or days with `dateDiff()`, `now()`, and `interval` like `dateDiff('minute', timestamp, now()) < 30`.

- Creating percentages by calculating the sum of one property over the sum of all related properties inline with `sum()`, `/`, `+`, and `*` like `sumIf(1, properties.$browser = 'Chrome') / sumIf(1, properties.$browser = 'Safari' or properties.$browser = 'Chrome')`

- Binning events based on time of day, week, and month with `toHour`, `toDayOfWeek`, `toStartOfWeek`, `toMonth` like `multiIf(5 >= toHour(timestamp) and toHour(timestamp) < 12, 'morning', 12 >= toHour(timestamp) and toHour(timestamp) < 17, 'afternoon', 'night')`

- Breaking down by multiple properties using `concat()` like `concat(properties.$os_name, ' - ', properties.$os_version)`.

- Matching URL patterns with `like` like `(properties.$current_url LIKE '%/blog%')`

- Filter null property values with `IS NOT NULL` like `person.properties.$initial_utm_source IS NOT NULL`.

- Breakdown by values in an [array](/tutorials/array-filter-breakdown.md) by using a combination of `JSONExtractArrayRaw` and `arrayJoin` like `arrayJoin(JSONExtractArrayRaw(properties.$active_feature_flags ?? '[]'), ',')`.

- Extracting the ID from [autocaptured elements](/tutorials/hogql-autocapture.md) like `extract(elements_chain, '[:|"]attr__id="(.*?)"')`.
""".strip()

# Copied from https://posthog.com/docs/sql/clickhouse-functions.md
SQL_SUPPORTED_FUNCTIONS_DOCS = r"""
This is an [ever-expanding](https://github.com/posthog/posthog/blob/master/posthog/hogql/constants.py) list of enabled ClickHouse functions.

You can find their full definitions in the [ClickHouse documentation](https://clickhouse.com/docs/en/sql-reference/functions). Additionally, we include a list of popular ones and their uses in the [HogQL expressions](/docs/hogql/expressions#functions-and-aggregations.md) and [SQL insight](/docs/product-analytics/sql#useful-functions.md) documentation.

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
"""

# Copied from https://posthog.com/docs/hogql/aggregations.md
SQL_SUPPORTED_AGGREGATIONS_DOCS = r"""
This is an [ever-expanding](https://github.com/PostHog/posthog/blob/dfce91d924fe038568c626416fa23e67d0f0906f/posthog/hogql/constants.py#L489) list of enabled aggregations.

You can find their full definitions in the [ClickHouse documentation](https://clickhouse.com/docs/en/sql-reference/aggregate-functions/reference). Additionally, we include a list of popular ones and their uses in the [HogQL expressions](/docs/hogql/expressions#functions-and-aggregations.md) and [SQL insight](/docs/product-analytics/sql#useful-functions.md) documentation.

## Standard aggregate functions

- `count`
- `countIf`
- `min`
- `minIf`
- `max`
- `maxIf`
- `sum`
- `sumIf`
- `avg`
- `avgIf`
- `any`
- `anyIf`
- `stddevPop`
- `stddevPopIf`
- `stddevSamp`
- `stddevSampIf`
- `varPop`
- `varPopIf`
- `varSamp`
- `varSampIf`
- `covarPop`
- `covarPopIf`
- `covarSamp`
- `covarSampIf`

## ClickHouse-specific aggregate functions

- `anyHeavy`
- `anyHeavyIf`
- `anyLast`
- `anyLastIf`
- `argMin`
- `argMinIf`
- `argMax`
- `argMaxIf`
- `avgWeighted`
- `avgWeightedIf`
- `groupArray`
- `groupUniqArray`
- `groupArrayInsertAt`
- `groupArrayInsertAtIf`
- `groupArrayMovingAvg`
- `groupArrayMovingAvgIf`
- `groupArrayMovingSum`
- `groupArrayMovingSumIf`
- `groupBitAnd`
- `groupBitAndIf`
- `groupBitOr`
- `groupBitOrIf`
- `groupBitXor`
- `groupBitXorIf`
- `groupBitmap`
- `groupBitmapIf`
- `groupBitmapAnd`
- `groupBitmapAndIf`
- `groupBitmapOr`
- `groupBitmapOrIf`
- `groupBitmapXor`
- `groupBitmapXorIf`
- `sumWithOverflow`
- `sumWithOverflowIf`
- `deltaSum`
- `deltaSumIf`
- `deltaSumTimestamp`
- `deltaSumTimestampIf`
- `sumMap`
- `sumMapIf`
- `minMap`
- `minMapIf`
- `maxMap`
- `maxMapIf`
- `skewSamp`
- `skewSampIf`
- `skewPop`
- `skewPopIf`
- `kurtSamp`
- `kurtSampIf`
- `kurtPop`
- `kurtPopIf`
- `uniq`
- `uniqIf`
- `uniqExact`
- `uniqExactIf`
- `uniqHLL12`
- `uniqHLL12If`
- `uniqTheta`
- `uniqThetaIf`
- `simpleLinearRegression`
- `simpleLinearRegressionIf`
- `contingency`
- `contingencyIf`
- `cramersV`
- `cramersVIf`
- `cramersVBiasCorrected`
- `cramersVBiasCorrectedIf`
- `theilsU`
- `theilsUIf`
- `maxIntersections`
- `maxIntersectionsIf`
- `maxIntersectionsPosition`
- `maxIntersectionsPositionIf`
"""
