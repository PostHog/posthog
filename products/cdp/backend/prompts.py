from collections.abc import Iterable, Iterator

# nosemgrep: python.lang.security.use-defused-xml.use-defused-xml (XML generation only, no parsing - no XXE risk)
from xml.etree import ElementTree as ET

from posthog.schema import PropertyOperator

from posthog.taxonomy.taxonomy import CoreFilterDefinition, visible_definitions

from products.cdp.backend.models.hog_functions.hog_function import TYPES_WITH_TRANSPILED_FILTERS, HogFunctionType

from ee.hogai.summarizers.property_filters import PROPERTY_FILTER_VERBOSE_NAME

# `flag_evaluates_to` compiles only on a `type: "flag"` filter. Hog function filters are only ever
# event, person, or group, and `property_to_expr` raises `NotImplementedError` for those.
UNSUPPORTED_FILTER_OPERATORS = frozenset({PropertyOperator.FLAG_EVALUATES_TO})

# These operators emit `sortableSemver` and `multiSearchAnyCaseInsensitive`, which the JavaScript
# STL never defines. On the types that transpile filters instead of compiling bytecode, a filter
# using one saves without error and then throws `ReferenceError` on the first event.
JS_UNSUPPORTED_FILTER_OPERATORS = frozenset(
    {
        PropertyOperator.SEMVER_EQ,
        PropertyOperator.SEMVER_NEQ,
        PropertyOperator.SEMVER_GT,
        PropertyOperator.SEMVER_GTE,
        PropertyOperator.SEMVER_LT,
        PropertyOperator.SEMVER_LTE,
        PropertyOperator.SEMVER_TILDE,
        PropertyOperator.SEMVER_CARET,
        PropertyOperator.SEMVER_WILDCARD,
        PropertyOperator.ICONTAINS_MULTI,
        PropertyOperator.NOT_ICONTAINS_MULTI,
    }
)

# Transformations run during ingestion against `TRANSFORMATION_AVAILABLE_GLOBALS`, which holds no
# `person` and no group slots, so a person or group filter evaluates against null and never matches.
# `HogFunctionFilters` hides those taxonomic groups for the same reason.
TYPES_WITHOUT_PERSON_GLOBALS = frozenset(
    {HogFunctionType.TRANSFORMATION.value, HogFunctionType.TRANSFORMATION_LOG.value}
)

# Stands in for <person_property_taxonomy> on the types that have no person globals.
EVENT_ONLY_FILTER_SCOPE = (
    "<filter_scope><usage>This function runs during ingestion, where only the event is in scope. "
    "Use `event` property filters only. A `person` or `group` filter saves without error and then "
    "matches nothing, so the function never runs.</usage></filter_scope>"
)

HOG_TRANSFORMATION_ASSISTANT_ROOT_SYSTEM_PROMPT = """
The user is currently editing or creating a Hog transformation function. They expect your help with writing and tweaking Hog code.

IMPORTANT: This is currently your primary task. Therefore `create_hog_transformation_function` is currently your primary tool.
Use `create_hog_transformation_function` when answering ANY requests remotely related to writing Hog code or to transforming data (including filtering, mappings, inputs and other operations).
It's very important to disregard other tools for these purposes - the user expects `create_hog_transformation_function`.

NOTE: When calling the `create_hog_transformation_function` tool, do not provide any response other than the tool call.

After the tool completes, do NOT repeat the code, as the user can see it. Only summarize the changes, comprehensively, but in only one brief sentence.
"""

HOG_FUNCTION_INPUTS_ASSISTANT_ROOT_SYSTEM_PROMPT = """
The user is currently editing or creating input variables for a Hog function. They expect your help with generating and managing input schemas.

IMPORTANT: This is currently your primary task. Therefore `create_hog_function_inputs` is currently your primary tool.
Use `create_hog_function_inputs` when answering ANY requests remotely related to creating, modifying, or managing input variables for hog functions.
It's very important to disregard other tools for these purposes - the user expects `create_hog_function_inputs`.

NOTE: When calling the `create_hog_function_inputs` tool, do not provide any response other than the tool call.

After the tool completes, do NOT repeat the schema, as the user can see it. Only summarize the changes, comprehensively, but in only one brief sentence.
"""

HOG_FUNCTION_FILTERS_ASSISTANT_ROOT_SYSTEM_PROMPT = """
The user is currently setting up filters for a Hog function. They expect your help with configuring which events and properties should trigger the function.

IMPORTANT: This is currently your primary task. Therefore `create_hog_function_filters` is currently your primary tool.
Use `create_hog_function_filters` when answering ANY requests remotely related to setting up filters, event matching, property filtering, or trigger conditions for hog functions.
It's very important to disregard other tools for these purposes - the user expects `create_hog_function_filters`.

NOTE: When calling the `create_hog_function_filters` tool, do not provide any response other than the tool call.

After the tool completes, do NOT repeat the filter configuration, as the user can see it. Only summarize the changes, comprehensively, but in only one brief sentence.
"""

IDENTITY_MESSAGE_HOG = """Hog is PostHog's own programming language. You write Hog code based on a prompt. You don't help with other knowledge.

Here is the Hog standard library. Dont use any other functions since they are not supported in Hog:

Hog's standard library
Hog's standard library includes the following functions and will expand. To see the the most update-to-date list, check the Python VM's stl/__init__.py file.

Type conversion
toString(arg: any): string
toUUID(arg: any): UUID
toInt(arg: any): integer
toFloat(arg: any): float
toDate(arg: string | integer): Date
toDateTime(arg: string | integer): DateTime
tuple(...args: any[]): tuple
typeof(arg: any): string
Comparisons
ifNull(value: any, alternative: any)
String functions
print(...args: any[])
concat(...args: string[]): string
match(arg: string, regex: string): boolean
length(arg: string): integer
empty(arg: string): boolean
notEmpty(arg: string): boolean
lower(arg: string): string
upper(arg: string): string
reverse(arg: string): string
trim(arg: string, char?: string): string
trimLeft(arg: string, char?: string): string
trimRight(arg: string, char?: string): string
splitByString(separator: string, str: string, maxParts?: integer): string[]
jsonParse(arg: string): any
jsonStringify(arg: object, indent = 0): string
base64Encode(arg: string): string
base64Decode(arg: string): string
tryBase64Decode(arg: string): string
encodeURLComponent(arg: string): string
decodeURLComponent(arg: string): string
replaceOne(arg: string, needle: string, replacement: string): string
replaceAll(arg: string, needle: string, replacement: string): string
generateUUIDv4(): string
position(haystack: string, needle: string): integer
positionCaseInsensitive(haystack: string, needle: string): integer
substring(arg: string, offset: integer, length?: integer): string
Objects and arrays
length(arg: any[] | object): integer
empty(arg: any[] | object): boolean
notEmpty(arg: any[] | object): boolean
keys(arg: any[] | object): string[]
vaues(arg: any[] | object): string[]
indexOf(array: any[], elem: any): integer
has(array: any[], element: any)
arrayPushBack(arr: any[], value: any): any[]
arrayPushFront(arr: any[], value: any): any[]
arrayPopBack(arr: any[]): any[]
arrayPopFront(arr: any[]): any[]
arraySort(arr: any[]): any[]
arrayReverse(arr: any[]): any[]
arrayReverseSort(arr: any[]): any[]
arrayStringConcat(arr: any[], separator?: string): string
arrayMap(callback: (arg: any): any, array: any[]): any[]
arrayFilter(callback: (arg: any): boolean, array: any[]): any[]
arrayExists(callback: (arg: any): boolean, array: any[]): boolean
arrayCount(callback: (arg: any): boolean, array: any[]): integer
Date functions
now(): DateTime
toUnixTimestamp(input: DateTime | Date | string, zone?: string): float
fromUnixTimestamp(input: number): DateTime
toUnixTimestampMilli(input: DateTime | Date | string, zone?: string): float
fromUnixTimestampMilli(input: integer | float): DateTime
toTimeZone(input: DateTime, zone: string): DateTime | Date
toDate(input: string | integer | float): Date
toDateTime(input: string | integer | float, zone?: string): DateTime
formatDateTime(input: DateTime, format: string, zone?: string): string - we use use the ClickHouse formatDateTime syntax.
toInt(arg: any): integer - Converts arg to a 64-bit integer. Converts Dates into days from epoch, and DateTimes into seconds from epoch
toFloat(arg: any): float - Converts arg to a 64-bit float. Converts Dates into days from epoch, and DateTimes into seconds from epoch
toDate(arg: string | integer): Date - arg must be a string YYYY-MM-DD or a Unix timestamp in seconds
toDateTime(arg: string | integer): DateTime - arg must be an ISO timestamp string or a Unix timestamp in seconds
Cryptographic functions
md5Hex(arg: string): string
sha256Hex(arg: string): string
sha256HmacChainHex(arg: string[]): string

Here are examples of the syntax. Do not use any other functions since they are not supported in Hog:

Syntax
Comments
Hog comments start with //. You can also use SQL style comments with -- or C++ style multi line blocks with /*.

// Hog comments start with //
-- You can also use SQL style comments with --
/* or C++ style multi line
blocks */
Variables
Use := to assign a value to a variable because = is just equals in SQL.

// assign 12 to myVar
let myVar := 12
myVar := 13
myVar := myVar + 1
Comparisons
On top of standard comparisons, like, ilike, not like, and not ilike work.

let myVar := 12
print(myVar = 12 or myVar < 10) // prints true
print(myVar < 12 and myVar > 12) // prints false

let string := 'mystring'
print(string ilike '%str%') // prints true
Regex
Compares strings against regex patterns. =~ matches exactly, =~* matches case insensitively, !~ does not match, and !~* does not match case insensitively.

print('string' =~ 'i.g$') // true
print('string' !~ 'i.g$') // false
print('string' =~* 'I.G$') // true, case insensitive
print('string' !~* 'I.G$') // false, case insensitive
Arrays
Supports both dot notation and bracket notation.

Arrays in Hog (and our SQL flavor) are 1-indexed!

let myArray := [1,2,3]
print(myArray.2) // prints 2
print(myArray[2]) // prints 2
Tuples
Supports both dot notation and bracket notation.

Tuples in Hog (and our SQL flavor) are 1-indexed!

let myTuple := (1,2,3)
print(myTuple.2) // prints 2
print(myTuple[2]) // prints 2
Objects
You must use single quotes for object keys and values.

let myObject := {'key': 'value'}
print(myObject.key) // prints 'value'
print(myObject['key']) // prints 'value'

print(myObject?.this?.is?.not?.found) // prints 'null'
print(myObject?.['this']?.['is']?.not?.found) // prints 'null'
Strings
Strings must always start and end with a single quote. Includes f-string support.

let str := 'string'
print(str || ' world') // prints 'string world', SQL concat
print(f'hello {str}') // prints 'hello string'
print(f'hello {f'{str} world'}') // prints 'hello string world'
String truncation
// Truncate a string to a maximum length
if (length(s) > 2000) {
    s := substring(s, 1, 2000)
}
Functions and lambdas
Functions are first class variables, just like in JavaScript. You can define them with fun, or inline as lambdas:

fun addNumbers(num1, num2) {
    let newNum := num1 + num2
    return newNum
}
print(addNumbers(1, 2))

let square := (a) -> a * a
print(square(4))
See Hog's standard library for a list of built-in functions.

Logic

let a := 3
if (a > 0) {
    print('yes')
}
Ternary operations

print(a < 2 ? 'small' : 'big')
Nulls

let a := null
print(a ?? 'is null') // prints 'is null'
While loop

let i := 0
while(i < 3) {
    print(i) // prints 0, 1, 2
    i := i + 1
}
For loop

for(let i := 0; i < 3; i := i + 1) {
    print(i) // prints 0, 1, 2
}
For-in loop

let arr = ['banana', 'tomato', 'potato']
for (let food in arr) {
    print(food)
}

let obj = {'banana': 3, 'tomato': 5, 'potato': 6}
for (let food, value in arr) {
    print(food, value)
}

Here are some more rules around Hog:

Here are a few key differences compared to other programming languages:

- Variable assignment in Hog is done with the := operator, as = and == are both used for equality comparisons in SQL
- You must type out and, or and not. Currently && and ! raise syntax errors, whereas || is used as the string concatenation operator.
- All arrays in Hog start from index 1. Yes, for real. Trust us, we know. However that's how SQL has always worked, so we adopted it.
- The easiest way to debug your code is to print() the variables in question, and then check the logs.
- Strings must always be written with 'single quotes'. You may use f-string templates like f'Hello {name}'.
- Never use arr[a:b]; Hog does not support slice syntax. Use substring(str, offset, length) for strings.
- delete does not work in Hog.

"""

HOG_EXAMPLE_MESSAGE = """
Here are some valid Hog code examples:
// Example 1: PII Data Hashing
// Get the properties to hash from inputs and split by comma
let propertiesToHash := []
if (notEmpty(inputs.propertiesToHash)) {
    propertiesToHash := splitByString(',', inputs.propertiesToHash)
}
let hashDistinctId := inputs.hashDistinctId
let salt := inputs.salt
if (empty(propertiesToHash) and not hashDistinctId) {
    return event
}
// Create a deep copy of the event to modify
let returnEvent := event
// Helper function to get nested property value
fun getNestedValue(obj, path) {
    let parts := splitByString('.', path)
    let current := obj
    for (let part in parts) {
        if (current = null) {
            return null
        }
        current := current[part]
    }
    return current
}
// Helper function to set nested property value
fun setNestedValue(obj, path, value) {
    let parts := splitByString('.', path)
    let current := obj
    // Navigate to the parent object of the target property
    for (let i := 1; i < length(parts); i := i + 1) {
        let part := parts[i]
        if (current[part] = null) {
            current[part] := {}
        }
        current := current[part]
    }
    // Set the value on the last part
    let lastPart := parts[length(parts)]
    current[lastPart] := value
}
// Hash distinct_id if enabled also potentially using a salt
if (hashDistinctId and notEmpty(event.distinct_id)) {
    if(notEmpty(salt)) {
        returnEvent.distinct_id := sha256Hex(concat(toString(event.distinct_id), salt))
    } else {
        returnEvent.distinct_id := sha256Hex(toString(event.distinct_id))
    }
}
// Hash each property value potentially using a salt
for (let _, path in propertiesToHash) {
    let value := getNestedValue(event.properties, trim(path))  // Trim to handle spaces after commas
    if (notEmpty(value)) {
        if(notEmpty(salt)) {
            let hashedValue := sha256Hex(concat(toString(value), salt))
            setNestedValue(returnEvent.properties, trim(path), hashedValue)
        } else {
            let hashedValue := sha256Hex(toString(value))
            setNestedValue(returnEvent.properties, trim(path), hashedValue)
        }
    }
}
return returnEvent
// Example 2: GeoIP Enrichment
// Define the properties to be added to the event
let geoipProperties := {
    'city_name': null,
    'city_confidence': null,
    'subdivision_2_name': null,
    'subdivision_2_code': null,
    'subdivision_1_name': null,
    'subdivision_1_code': null,
    'country_name': null,
    'country_code': null,
    'continent_name': null,
    'continent_code': null,
    'postal_code': null,
    'latitude': null,
    'longitude': null,
    'accuracy_radius': null,
    'time_zone': null
}
// Check if the event has an IP address
if (event.properties?.$geoip_disable or empty(event.properties?.$ip)) {
    print('geoip disabled or no ip.')
    return event
}
let ip := event.properties.$ip
if (ip == '127.0.0.1') {
    print('spoofing ip for local development', ip)
    ip := '89.160.20.129'
}
let response := geoipLookup(ip)
if (not response) {
    print('geoip lookup failed for ip', ip)
    return event
}
let location := {}
if (response.city) {
    location['city_name'] := response.city.names?.en
}
if (response.country) {
    location['country_name'] := response.country.names?.en
    location['country_code'] := response.country.isoCode
}
if (response.continent) {
    location['continent_name'] := response.continent.names?.en
    location['continent_code'] := response.continent.code
}
if (response.postal) {
    location['postal_code'] := response.postal.code
}
if (response.location) {
    location['latitude'] := response.location?.latitude
    location['longitude'] := response.location?.longitude
    location['accuracy_radius'] := response.location?.accuracyRadius
    location['time_zone'] := response.location?.timeZone
}
if (response.subdivisions) {
    for (let index, subdivision in response.subdivisions) {
        location[f'subdivision_{index + 1}_code'] := subdivision.isoCode
        location[f'subdivision_{index + 1}_name'] := subdivision.names?.en
    }
}
print('geoip location data for ip:', location)
let returnEvent := event
returnEvent.properties := returnEvent.properties ?? {}
returnEvent.properties.$set := returnEvent.properties.$set ?? {}
returnEvent.properties.$set_once := returnEvent.properties.$set_once ?? {}
for (let key, value in geoipProperties) {
    if (value != null) {
        returnEvent.properties.$set[f'$geoip_{key}'] := value
        returnEvent.properties.$set_once[f'$initial_geoip_{key}'] := value
    }
    returnEvent.properties.$set[f'$geoip_{key}'] := value
    returnEvent.properties.$set_once[f'$initial_geoip_{key}'] := value
}
for (let key, value in location) {
    returnEvent.properties[f'$geoip_{key}'] := value
    returnEvent.properties.$set[f'$geoip_{key}'] := value
    returnEvent.properties.$set_once[f'$initial_geoip_{key}'] := value
}
return returnEvent
// Example 3: IP Anonymization
// Check if the event has an IP address
if (empty(event.properties?.$ip)) {
    print('No IP address found in event')
    return event
}
let ip := event.properties.$ip
let parts := splitByString('.', ip)
// Check if we have exactly 4 parts for IPv4
if (length(parts) != 4) {
    print('Invalid IP address format: wrong number of octets')
    return event
}
// Validate each octet is a number between 0 and 255
for (let i := 1; i <= 4; i := i + 1) {
    let octet := toInt(parts[i])
    if (octet = null or octet < 0 or octet > 255) {
        print('Invalid IP address: octets must be numbers between 0 and 255')
        return event
    }
}
// Replace the last octet with '0'
let anonymizedIp := concat(parts[1], '.', parts[2], '.', parts[3], '.0')
let returnEvent := event
returnEvent.properties.$ip := anonymizedIp
return returnEvent
// Example 4: URL Parameter Masking
// Function to check if parameter matches any mask pattern
fun isParameterInList(paramName, paramsString) {
    let paramsList := splitByString(',', paramsString)
    for (let pattern in paramsList) {
        if (lower(paramName) =~ lower(trim(pattern))) {
            return true
        }
    }
    return false
}

// Function to mask URL parameters
fun maskURLParameters(url, paramsToMask, maskValue) {
    // If URL is empty or not a string, return as is
    if (empty(url) or typeof(url) != 'string') {
        return url
    }
        // Split URL into base and query string
        let parts := splitByString('?', url, 2)
        if (length(parts) < 2) {
            return url
        }
        let baseUrl := parts[1]
        let queryString := parts[2]
        // Handle malformed URLs that start with ?
        if (empty(baseUrl)) {
            return url
        }
        // Split query string into parameters
        let params := splitByString('&', queryString)
        let maskedParams := []
        // Process each parameter
        for (let param in params) {
            if (not empty(param)) {
                let keyValue := splitByString('=', param, 2)
                let paramName := keyValue[1]
                // Handle parameters without values (e.g., ?key&foo=bar)
                if (length(keyValue) < 2) {
                    if (isParameterInList(paramName, paramsToMask)) {
                        maskedParams := arrayPushBack(maskedParams, concat(paramName, '=', maskValue))
                    } else {
                        maskedParams := arrayPushBack(maskedParams, paramName)
                    }
                } else {
                    if (isParameterInList(paramName, paramsToMask)) {
                        maskedParams := arrayPushBack(maskedParams, concat(paramName, '=', maskValue))
                    } else {
                        maskedParams := arrayPushBack(maskedParams, param)
                    }
                }
            }
        }
        // Reconstruct URL with masked parameters
        return concat(baseUrl, '?', arrayStringConcat(maskedParams, '&'))
    } catch (error) {
        print('Error masking URL parameters:', error)
        return url
    }
}
// Create a copy of the event to modify
let maskedEvent := event
// Process each URL property
for (let propName, paramsToMask in inputs.urlProperties) {
    if (not empty(event.properties?.[propName])) {
        maskedEvent.properties[propName] := maskURLParameters(
            event.properties[propName],
            paramsToMask,
            inputs.maskWith
        )
    }
}
return maskedEvent
// Example 5: Filter Properties
// Check if the event has properties
if (empty(event.properties)) {
    return event
}
let returnEvent := event
let propertiesToFilter := splitByString(',', inputs.propertiesToFilter)
// Process each property to filter
let i := 1
while (i <= length(propertiesToFilter)) {
    let prop := trim(propertiesToFilter[i])
    if (not empty(prop)) {
        let parts := splitByString('.', prop)
        let current := returnEvent.properties
        let found := true
        // Navigate to the parent object
        let j := 1
        while (j < length(parts) and found) {
            if (not has(keys(current), parts[j])) {
                found := false
            } else {
                current := current[parts[j]]
            }
            j := j + 1
        }
        // Handle the last part if we found the parent object
        if (found and j == length(parts)) {
            let lastPart := parts[length(parts)]
            if (has(keys(current), lastPart)) {
                current[lastPart] := null
            }
        }
    }
    i := i + 1
}
return returnEvent"""


TRANSFORMATION_LIMITATIONS_MESSAGE = """PostHog Transformations can only modify individual incoming events. They cannot access or read person properties, historical data, or global state, because they run before person resolution. Their only purpose is to transform the structure of a single event (e.g., add properties, rename fields, enrich data) before ingestion. This means they cannot perform logic that depends on previous values, such as incrementing a count or checking if a property already exists."""

TRANSFORMATION_STRUCTURE_MESSAGE = """A Hog transformation is a top-level script, NOT a wrapped function.

Required contract:
- `event` is available as an implicit global - do NOT declare parameters or wrap the top level in a function
- Code runs once per incoming event
- End with `return event` (or a modified copy) to keep the event, or `return null` to drop it
- You MAY define helper functions with `fun name(args) { ... }` and call them from the top level, but the main logic must live at the top level

DO NOT produce a script like this - it defines an unused function and is a no-op at runtime (this shape is for site destinations/site apps, not transformations):

    fun onEvent(event) {
        // ...
        return event
    }

Correct structure:

    let returnEvent := event
    // ...modifications on returnEvent...
    return returnEvent
"""
DESTINATION_LIMITATIONS_MESSAGE = """PostHog Destinations have access to the event properties, including person properties and group properties. Just like Transformations they cannot perform logic that depends on previous values, such as incrementing a count or checking if a property already exists."""

HOG_GRAMMAR_MESSAGE = """
Here is the grammar for Hog:
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
subsequentSelectSetClause: (EXCEPT ALL | EXCEPT | UNION ALL (BY NAME)? | UNION DISTINCT (BY NAME)? | UNION (BY NAME)? | INTERSECT ALL | INTERSECT DISTINCT | INTERSECT) selectStmtWithParens;
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
hogqlxChildElement: hogqlxTagElement | (LBRACE columnExpr RBRACE);
hogqlxTagElement
    : LT identifier hogqlxTagAttribute* SLASH GT                                          # HogqlxTagElementClosed
    | LT identifier hogqlxTagAttribute* GT hogqlxChildElement* LT SLASH identifier GT     # HogqlxTagElementNested
    ;
hogqlxTagAttribute
    :   identifier '=' string
    |   identifier '=' LBRACE columnExpr RBRACE
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
Leave out all comment string and return the hog code nicely formatted.
These functions are not available in the current version of HogQL (NEVER USE THEM):
- break
- continue
- left
- right
- arrayConcat
"""


def _render_taxonomy_group(
    definitions: Iterable[tuple[str, CoreFilterDefinition]], root_tag: str, entry_tag: str
) -> str:
    root = ET.Element(root_tag)
    for name, definition in definitions:
        entry = ET.SubElement(root, entry_tag)
        ET.SubElement(entry, "name").text = name
        if prop_type := definition.get("type"):
            ET.SubElement(entry, "type").text = prop_type
        if description := (
            definition.get("description_llm") or definition.get("description") or definition.get("label")
        ):
            ET.SubElement(entry, "description").text = description
        if examples := definition.get("examples"):
            ET.SubElement(entry, "examples").text = ", ".join(str(example) for example in examples)
    return ET.tostring(root, encoding="unicode")


def render_event_taxonomy() -> str:
    return _render_taxonomy_group(visible_definitions("events"), "event_taxonomy", "event")


def _filterable_event_properties() -> Iterator[tuple[str, CoreFilterDefinition]]:
    """Event properties a hog function filter can resolve, so the two the compiler mishandles are out."""
    for name, definition in visible_definitions("event_properties"):
        # A virtual property (e.g. `$virt_is_bot`) compiles to a bare top-level global the CDP
        # filter globals never define, so a filter on one throws at runtime. `distinct_id` compiles
        # to `properties.distinct_id`, but CDP stores the identifier at the top level, so an
        # event-type filter on it always evaluates false; `property_to_expr` special-cases
        # `type: "person", key: "distinct_id"`, so the person block is where it stays described.
        if definition.get("virtual") or name == "distinct_id":
            continue
        yield name, definition


def render_event_property_taxonomy() -> str:
    return _render_taxonomy_group(_filterable_event_properties(), "event_property_taxonomy", "property")


def render_person_property_taxonomy() -> str:
    # The taxonomy copies almost every event property onto the person, so a description here would
    # repeat <event_property_taxonomy> and nearly double the prompt. Describe only the names that
    # section does not carry, because the model has nowhere else to read their meaning.
    event_property_names = {name for name, _ in _filterable_event_properties()}
    root = ET.Element("person_property_taxonomy")
    ET.SubElement(root, "usage").text = (
        "A person property named like an event property means the same thing, so read its "
        "description in <event_property_taxonomy>. A `$initial_` prefix means the value from the "
        "first time the person was seen; without it, the value from the most recent time."
    )
    for name, definition in visible_definitions("person_properties"):
        # Virtual properties are computed in HogQL and are absent from the person record a hog
        # function filters against, so a filter on one saves cleanly and then never matches.
        if definition.get("virtual"):
            continue
        entry = ET.SubElement(root, "property")
        ET.SubElement(entry, "name").text = name
        if prop_type := definition.get("type"):
            ET.SubElement(entry, "type").text = prop_type
        if _is_person_only(name, event_property_names):
            if description := (definition.get("description_llm") or definition.get("description")):
                ET.SubElement(entry, "description").text = description
    return ET.tostring(root, encoding="unicode")


def _is_person_only(name: str, event_property_names: set[str]) -> bool:
    """True when the name has no counterpart in the event property taxonomy, in either form."""
    base = name.removeprefix("$initial_")
    return (
        name not in event_property_names and base not in event_property_names and f"${base}" not in event_property_names
    )


def render_filter_operator_taxonomy(function_type: str) -> str:
    unsupported = UNSUPPORTED_FILTER_OPERATORS
    if function_type in TYPES_WITH_TRANSPILED_FILTERS:
        unsupported = unsupported | JS_UNSUPPORTED_FILTER_OPERATORS
    root = ET.Element("filter_taxonomy")
    ET.SubElement(root, "usage").text = "A filter's `operator` field takes the `value` below, never the `meaning`."
    for operator, verbose_name in PROPERTY_FILTER_VERBOSE_NAME.items():
        if operator in unsupported:
            continue
        entry = ET.SubElement(root, "operator")
        ET.SubElement(entry, "value").text = operator.value
        ET.SubElement(entry, "meaning").text = verbose_name
    return ET.tostring(root, encoding="unicode")


HOG_FUNCTION_FILTERS_SYSTEM_PROMPT = """You are an expert at creating filters for PostHog hog functions.

Create filters based on the user's instructions. Return the filters as a JSON object with the following structure:
{
    "events": [
        {
            "id": "event_name",
            "name": "Event Name",
            "type": "events",
            "order": 0,
            "properties": []
        }
    ],
    "actions": [],
    "properties": [
        {
            "key": "property_key",
            "value": "property_value",
            "operator": "exact",
            "type": "event"
        }
    ],
    "filter_test_accounts": false
}

Property types can be:
- "event" for event properties
- "person" for person properties
- "group" for group properties

To match every event, leave "events" as an empty list. "All events" in <event_taxonomy> is a wildcard label, not an event name, so a filter using it as an "id" matches nothing.

Pick the operator that says what the user asked for. <filter_taxonomy> lists every one you may use.

Return ONLY the JSON object inside <filters> tags. Do not add any other text or explanation."""


def render_filters_system_prompt(function_type: str, current_filters: str) -> str:
    """The full system prompt for the filters tool, carrying only the taxonomy this type can filter on."""
    return "\n\n".join(
        [
            HOG_FUNCTION_FILTERS_SYSTEM_PROMPT,
            render_event_taxonomy(),
            render_event_property_taxonomy(),
            # The scope note takes the person block's place rather than preceding the taxonomy, so a
            # type that drops that block still shares every preceding byte with one that keeps it.
            EVENT_ONLY_FILTER_SCOPE
            if function_type in TYPES_WITHOUT_PERSON_GLOBALS
            else render_person_property_taxonomy(),
            render_filter_operator_taxonomy(function_type),
            # Last, so the taxonomy above stays an identical prefix across teams and requests
            # and the provider's prompt cache can hit it.
            f"Current filters: {current_filters}\nFunction type: {function_type}",
        ]
    )


HOG_FUNCTION_INPUTS_SYSTEM_PROMPT = """You are an expert at creating input variable schemas for PostHog hog functions.

Your task is to analyze the hog code and create appropriate input variable schemas based on the instructions.
CRITICAL: You must extract the EXACT variable names used in the hog code. Look for patterns like:
- inputs.variableName
- inputs['variableName']
- inputs["variableName"]
The "key" field in the schema MUST match exactly what is used in the hog code after "inputs.". For example:
- If code uses inputs.propertiesToRedact, the key must be "propertiesToRedact" (NOT "properties_to_redact")
- If code uses inputs.webhookUrl, the key must be "webhookUrl" (NOT "webhook_url")
- If code uses inputs.api_key, the key must be "api_key" (NOT "apiKey")

Return ONLY a valid JSON array of input schema objects inside <inputs_schema> tags."""

INPUT_SCHEMA_TYPES_MESSAGE = """Input schema format should be a list of objects with these fields:
- key: string (EXACT variable name as used in hog code, preserve camelCase/snake_case)
- type: string (one of: string, number, boolean, dictionary, choice, json, integration, integration_field, email)
- label: string (human readable label)
- description: string (description of what this input is for)
- required: boolean (whether this input is required)
- default: any (default value, optional)
- choices: list (for choice type, list of {label, value} objects)
- templating: boolean (whether templating is enabled, defaults to true)
- secret: boolean (whether this is a secret value, defaults to false)
- hidden: boolean (whether this input is hidden from users, defaults to false)
- integration: string (for integration type, the integration name)
- integration_key: string (for integration_field type, the integration key)
- integration_field: string (for integration_field type, the field name)
- requires_field: string (for conditional fields)
- requiredScopes: string (for integrations, required OAuth scopes)

export type CyclotronJobInputSchemaType = {
    type:
        | 'string'
        | 'number'
        | 'boolean'
        | 'dictionary'
        | 'choice'
        | 'json'
        | 'integration'
        | 'integration_field'
        | 'email'
    key: string
    label: string
    choices?: { value: string; label: string }[]
    required?: boolean
    default?: any
    secret?: boolean
    hidden?: boolean
    templating?: boolean
    description?: string
    integration?: string
    integration_key?: string
    integration_field?: string
    requires_field?: string
    requiredScopes?: string
}

Here are some example input schemas to help you understand the format:

Example 1 - Bot Detection Function:
[
    {
        "key": "userAgent",
        "type": "string",
        "label": "User Agent Property",
        "description": "The property that contains the user agent string (e.g. $raw_user_agent, $useragent)",
        "default": "$raw_user_agent",
        "secret": false,
        "required": true
    },
    {
        "key": "customBotPatterns",
        "type": "string",
        "label": "Custom Bot Patterns",
        "description": "Additional bot patterns to detect, separated by commas (e.g. mybot,customcrawler)",
        "default": "",
        "secret": false,
        "required": false
    },
    {
        "key": "customIpPrefixes",
        "type": "string",
        "label": "Custom IP Prefixes",
        "description": "Additional IPv4 or IPv6 prefixes in CIDR notation to block, separated by commas (e.g. 198.51.100.14/24,2001:db8::/48)",
        "default": "",
        "secret": false,
        "required": false
    }
]

Example 2 - Property Filter Function:
[
    {
        "key": "propertiesToFilter",
        "type": "string",
        "label": "Properties to filter",
        "description": "Comma-separated list of properties to filter (e.g. \"$set.email, $set.name, custom_prop\")",
        "required": true
    }
]

Example 3 - PII Hashing Function:
[
    {
        "key": "salt",
        "type": "string",
        "label": "Salt",
        "description": "A secret salt used for hashing. This should be kept secure and consistent.",
        "default": "",
        "secret": true,
        "required": true
    },
    {
        "key": "privateFields",
        "type": "string",
        "label": "Fields to hash",
        "description": "Comma-separated list of field names to hash. Can include both event properties and top-level event fields like distinct_id.",
        "default": "distinct_id,name,userid,email",
        "secret": false,
        "required": true
    },
    {
        "key": "includeSetProperties",
        "type": "boolean",
        "label": "Also hash $set and $set_once properties",
        "description": "Whether to also hash $set and $set_once properties that are used to update Person properties.",
        "default": true,
        "secret": false,
        "required": false
    }
]

Example 4 - Property Hashing Function:
[
    {
        "key": "propertiesToHash",
        "type": "string",
        "label": "Properties to Hash",
        "description": "Comma-separated list of property paths to hash (e.g. \"$ip,$email,$set.$phone\")",
        "default": "$ip",
        "secret": false,
        "required": true
    },
    {
        "key": "hashDistinctId",
        "type": "boolean",
        "label": "Hash Distinct ID",
        "description": "Whether to hash the distinct_id field",
        "default": false,
        "secret": false,
        "required": false
    },
    {
        "key": "salt",
        "type": "string",
        "label": "Salt",
        "description": "Optional salt to add to the hashed values for additional security",
        "default": "",
        "secret": true,
        "required": false
    }
]"""
