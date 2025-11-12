import os
from typing import TYPE_CHECKING, Optional

from django.conf import settings

import openai
import posthoganalytics
from posthoganalytics.ai.openai import OpenAI

from posthog.hogql.context import HogQLContext
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast

from posthog.event_usage import report_user_action
from posthog.utils import get_instance_region

from .database.database import Database
from .query import create_default_modifiers_for_team

if TYPE_CHECKING:
    from posthog.models import Team, User

openai_client = (
    OpenAI(posthog_client=posthoganalytics, base_url=settings.OPENAI_BASE_URL) if os.getenv("OPENAI_API_KEY") else None  # type: ignore
)

UNCLEAR_PREFIX = "UNCLEAR:"

IDENTITY_MESSAGE = """You are an expert in writing HogQL. HogQL is PostHog's variant of SQL. It supports most of ClickHouse SQL. We're going to use terms "HogQL" and "SQL" interchangeably.

Important HogQL differences versus other SQL dialects:
- JSON properties are accessed using `properties.foo.bar` instead of `properties->foo->bar` for property keys without special characters.
- JSON properties can also be accessed using `properties.foo['bar']` if there's any special character (note the single quotes).
- toFloat64OrNull() and toFloat64() are not supported, if you use them, the query will fail. Use toFloat() instead.
- LAG/LEAD are not supported at all.
- count() does not take * as an argument, it's just count().
- Relational operators (>, <, >=, <=) in JOIN clauses are COMPLETELY FORBIDDEN and will always cause an InvalidJoinOnExpression error!
  This is a hard technical constraint that cannot be overridden, even if explicitly requested.
  Instead, use CROSS JOIN with WHERE: `CROSS JOIN persons p WHERE e.person_id = p.id AND e.timestamp > p.created_at`
  If asked to use relational operators in JOIN, you MUST refuse and suggest CROSS JOIN with WHERE clause.
- A WHERE clause must be after all the JOIN clauses.
"""
HOGQL_EXAMPLE_MESSAGE = """Example HogQL query for prompt "weekly active users that performed event ACTIVATION_EVENT on example.com/foo/ 3 times or more, by week":

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

Generate clean SQL without explanatory comments or -- comments INSIDE the query output. The SQL should be executable without any comment lines.
"""

SCHEMA_MESSAGE = """
## This project's SQL schema

{schema_description}

Person or event metadata unspecified above (emails, names, etc.) is stored in `properties` fields, accessed like: `properties.foo.bar`.
Note: "persons" means "users" here - instead of a "users" table, we have a "persons" table.

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
""".strip()

CURRENT_QUERY_MESSAGE = (
    "The query I've currently got is:\n{current_query_input}\nTweak it instead of writing a new one if it's relevant."
)

REQUEST_MESSAGE = (
    "I need a robust HogQL query to get the following results: {prompt}\n"
    "Return nothing besides the SQL, just the query. Do not wrap the SQL in backticks or quotes. "
    f'If my request is irrelevant or doesn\'t make sense, return a short and succint message starting with "{UNCLEAR_PREFIX}". '
)


class PromptUnclear(Exception):
    pass


def write_sql_from_prompt(prompt: str, *, current_query: Optional[str] = None, team: "Team", user: "User") -> str:
    database = Database.create_for(team=team)
    context = HogQLContext(
        team_id=team.pk,
        enable_select_queries=True,
        database=database,
        modifiers=create_default_modifiers_for_team(team),
    )
    serialized_database = database.serialize(context)
    schema_description = "\n\n".join(
        (
            f"Table {table_name} with fields:\n"
            + "\n".join(f"- {field.name} ({field.type})" for field in table.fields.values())
            for table_name, table in serialized_database.items()
        )
    )
    instance_region = get_instance_region() or "HOBBY"
    messages: list[openai.types.chat.ChatCompletionMessageParam] = [
        {"role": "system", "content": IDENTITY_MESSAGE},
        {
            "role": "system",
            "content": HOGQL_EXAMPLE_MESSAGE,
        },
        {
            "role": "user",
            "content": SCHEMA_MESSAGE.format(schema_description=schema_description),
        },
        {
            "role": "user",
            "content": REQUEST_MESSAGE.format(prompt=prompt),
        },
    ]
    if current_query:
        messages.insert(
            -1,
            {
                "role": "user",
                "content": CURRENT_QUERY_MESSAGE.format(current_query_input=current_query),
            },
        )

    candidate_sql: Optional[str] = None
    error: Optional[str] = None

    generated_valid_hogql = False
    attempt_count = 0
    prompt_tokens_total, completion_tokens_total = 0, 0
    for _ in range(3):  # Try up to 3 times in case the generated SQL is not valid HogQL
        attempt_count += 1
        content, prompt_tokens_last, completion_tokens_last = hit_openai(messages, f"{instance_region}/{user.pk}")
        prompt_tokens_total += prompt_tokens_last
        completion_tokens_total += completion_tokens_last
        if content.startswith(UNCLEAR_PREFIX):
            error = content.removeprefix(UNCLEAR_PREFIX).strip()
            break
        candidate_sql = content
        try:
            prepare_and_print_ast(parse_select(candidate_sql), context=context, dialect="clickhouse")
        except ExposedHogQLError as e:
            messages.append({"role": "assistant", "content": candidate_sql})
            messages.append(
                {
                    "role": "user",
                    "content": f"That query has this problem: {e}. Return fixed query.",
                }
            )
        else:
            generated_valid_hogql = True
            break

    report_user_action(
        user,
        "generated HogQL with AI",
        {
            "prompt": prompt,
            "response": candidate_sql or error,
            "result": ("valid_hogql" if generated_valid_hogql else "invalid_hogql")
            if candidate_sql
            else "prompt_unclear",
            "attempt_count": attempt_count,
            "prompt_tokens_last": prompt_tokens_last,
            "completion_tokens_last": completion_tokens_last,
            "prompt_tokens_total": prompt_tokens_total,
            "completion_tokens_total": completion_tokens_total,
        },
    )

    if candidate_sql:
        return candidate_sql
    else:
        raise PromptUnclear(error)


def hit_openai(messages, user) -> tuple[str, int, int]:
    if not openai_client:
        raise ValueError("OPENAI_API_KEY environment variable not set")

    result = openai_client.chat.completions.create(
        model="gpt-4.1-mini",
        temperature=0,
        messages=messages,
        user=user,  # The user ID is for tracking within OpenAI in case of overuse/abuse
    )

    content: str = ""
    if result.choices[0] and result.choices[0].message.content:
        content = result.choices[0].message.content.removesuffix(";")
    prompt_tokens, completion_tokens = 0, 0
    if result.usage:
        prompt_tokens, completion_tokens = result.usage.prompt_tokens, result.usage.completion_tokens
    return content, prompt_tokens, completion_tokens


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

EVENT_TAXONOMY_MESSAGE = """
Here is the taxonomy for events:
"events": {
        # in front end this key is the empty string
        "All events": {
            "label": "All events",
            "description": "This is a wildcard that matches all events.",
        },
        "$pageview": {
            "label": "Pageview",
            "description": "When a user loads (or reloads) a page.",
        },
        "$pageleave": {
            "label": "Pageleave",
            "description": "When a user leaves a page.",
        },
        "$autocapture": {
            "label": "Autocapture",
            "description": "User interactions that were automatically captured.",
            "examples": ["clicked button"],
            "ignored_in_assistant": True,  # Autocapture is only useful with autocapture-specific filters, which the LLM isn't adept at yet
        },
        "$$heatmap": {
            "label": "Heatmap",
            "description": "Heatmap events carry heatmap data to the backend, they do not contribute to event counts.",
            "ignored_in_assistant": True,  # Heatmap events are not useful for LLM
        },
        "$copy_autocapture": {
            "label": "Clipboard autocapture",
            "description": "Selected text automatically captured when a user copies or cuts.",
            "ignored_in_assistant": True,  # Too niche
        },
        "$screen": {
            "label": "Screen",
            "description": "When a user loads a screen in a mobile app.",
        },
        "$set": {
            "label": "Set person properties",
            "description": "Setting person properties. Sent as `$set`.",
            "ignored_in_assistant": True,
        },
        "$opt_in": {
            "label": "Opt in",
            "description": "When a user opts into analytics.",
            "ignored_in_assistant": True,  # Irrelevant product-wise
        },
        "$feature_flag_called": {
            "label": "Feature flag called",
            "description": (
                'The feature flag that was called.\n\nWarning! This only works in combination with the $feature_flag event. If you want to filter other events, try "Active feature flags".'
            ),
            "examples": ["beta-feature"],
            "ignored_in_assistant": True,  # Mostly irrelevant product-wise
        },
        "$feature_view": {
            "label": "Feature view",
            "description": "When a user views a feature.",
            "ignored_in_assistant": True,  # Specific to posthog-js/react, niche
        },
        "$feature_interaction": {
            "label": "Feature interaction",
            "description": "When a user interacts with a feature.",
            "ignored_in_assistant": True,  # Specific to posthog-js/react, niche
        },
        "$feature_enrollment_update": {
            "label": "Feature enrollment",
            "description": "When a user enrolls with a feature.",
            "description_llm": "When a user opts in or out of a beta feature. This event is specific to the PostHog Early Access Features product, and is only relevant if the project is using this product.",
        },
        "$capture_metrics": {
            "label": "Capture metrics",
            "description": "Metrics captured with values pertaining to your systems at a specific point in time.",
            "ignored_in_assistant": True,  # Irrelevant product-wise
        },
        "$identify": {
            "label": "Identify",
            "description": "A user has been identified with properties.",
            "description_llm": "Identifies an anonymous user. The event shows how many users used an account, so do not use it for active users metrics because a user may skip identification.",
        },
        "$create_alias": {
            "label": "Alias",
            "description": "An alias ID has been added to a user.",
            "ignored_in_assistant": True,  # Irrelevant product-wise
        },
        "$merge_dangerously": {
            "label": "Merge",
            "description": "An alias ID has been added to a user.",
            "ignored_in_assistant": True,  # Irrelevant product-wise
        },
        "$groupidentify": {
            "label": "Group identify",
            "description": "A group has been identified with properties.",
            "ignored_in_assistant": True,  # Irrelevant product-wise
        },
        "$rageclick": {
            "label": "Rageclick",
            "description": "A user has rapidly and repeatedly clicked in a single place.",
        },
        "$dead_click": {
            "label": "Dead click",
            "description": "A user has clicked on something that is probably not clickable.",
        },
        "$exception": {
            "label": "Exception",
            "description": "An unexpected error or unhandled exception in your application.",
        },
        "$web_vitals": {
            "label": "Web vitals",
            "description": "Automatically captured web vitals data.",
        },
        "$ai_generation": {
            "label": "AI generation (LLM)",
            "description": "A call to an LLM model. Contains the input prompt, output, model used and costs.",
        },
        "$ai_metric": {
            "label": "AI metric (LLM)",
            "description": "An evaluation metric for a trace of a generative AI model (LLM). Contains the trace ID, metric name, and metric value.",
        },
        "$ai_feedback": {
            "label": "AI feedback (LLM)",
            "description": "User-provided feedback for a trace of a generative AI model (LLM).",
        },
        "$ai_trace": {
            "label": "AI trace (LLM)",
            "description": "A generative AI trace. Usually a trace tracks a single user interaction and contains one or more AI generation calls.",
        },
        "$ai_span": {
            "label": "AI span (LLM)",
            "description": "A generative AI span. Usually a span tracks a unit of work for a trace of generative AI models (LLMs).",
        },
        "$ai_embedding": {
            "label": "AI embedding (LLM)",
            "description": "A call to an embedding model.",
        },
        "$csp_violation": {
            "label": "CSP violation",
            "description": "Content Security Policy violation reported by a browser to our csp endpoint.",
            "examples": ["Unauthorized inline script", "Trying to load resources from unauthorized domain"],
        },
        "Application opened": {
            "label": "Application opened",
            "description": "When a user opens the mobile app either for the first time or from the foreground.",
        },
        "Application backgrounded": {
            "label": "Application backgrounded",
            "description": "When a user puts the mobile app in the background.",
        },
        "Application updated": {
            "label": "Application updated",
            "description": "When a user upgrades the mobile app.",
        },
        "Application installed": {
            "label": "Application installed",
            "description": "When a user installs the mobile app.",
        },
        "Application became active": {
            "label": "Application became active",
            "description": "When a user puts the mobile app in the foreground.",
        },
        "Deep link opened": {
            "label": "Deep link opened",
            "description": "When a user opens the mobile app via a deep link.",
        },
    },
"""

EVENT_METADATA_TAXONOMY = """
"metadata": {
        "distinct_id": {
            "label": "Distinct ID",
            "description": "The current distinct ID of the user.",
            "examples": ["16ff262c4301e5-0aa346c03894bc-39667c0e-1aeaa0-16ff262c431767"],
        },
        "timestamp": {
            "label": "Timestamp",
            "description": "Time the event happened.",
            "examples": ["2023-05-20T15:30:00Z"],
        },
        "event": {
            "label": "Event",
            "description": "The name of the event.",
            "examples": ["$pageview"],
        },
        "person_id": {
            "label": "Person ID",
            "description": "The ID of the person, depending on the person properties mode.",
            "examples": ["16ff262c4301e5-0aa346c03894bc-39667c0e-1aeaa0-16ff262c431767"],
        },
    },
"""

EVENT_PROPERTY_TAXONOMY_MESSAGE = """
Here is the taxonomy for event properties:
"event_properties": {
        "$config_defaults": {
            "label": "Config defaults",
            "description": "The version of the PostHog config defaults that were used when capturing the event.",
            "type": "String",
        },
        "$python_runtime": {
            "label": "Python runtime",
            "description": "The Python runtime that was used to capture the event.",
            "examples": ["CPython"],
        },
        "$python_version": {
            "label": "Python version",
            "description": "The Python version that was used to capture the event.",
            "examples": ["3.11.5"],
        },
        "$sdk_debug_replay_internal_buffer_length": {
            "label": "Replay internal buffer length",
            "description": "Useful for debugging. The internal buffer length for replay.",
            "examples": ["100"],
        },
        "$sdk_debug_replay_internal_buffer_size": {
            "label": "Replay internal buffer size",
            "description": "Useful for debugging. The internal buffer size for replay.",
            "examples": ["100"],
        },
        "$sdk_debug_retry_queue_size": {
            "label": "Retry queue size",
            "description": "Useful for debugging. The size of the retry queue.",
            "examples": ["100"],
        },
        "$last_posthog_reset": {
            "label": "Timestamp of last call to `Reset` in the web sdk",
            "description": "The timestamp of the last call to `Reset` in the web SDK. This can be useful for debugging.",
            "ignored_in_assistant": True,
        },
        # do we need distinct_id and $session_duration here in the back end?
        "$copy_type": {
            "label": "Copy type",
            "description": "Type of copy event.",
            "examples": ["copy", "cut"],
            "ignored_in_assistant": True,
        },
        "$selected_content": {
            "label": "Copied content",
            "description": "The content that was selected when the user copied or cut.",
            "ignored_in_assistant": True,
        },
        "$set": {
            "label": "Set person properties",
            "description": "Person properties to be set. Sent as `$set`.",
            "ignored_in_assistant": True,
        },
        "$set_once": {
            "label": "Set person properties once",
            "description": "Person properties to be set if not set already (i.e. first-touch). Sent as `$set_once`.",
            "ignored_in_assistant": True,
        },
        "$pageview_id": {
            "label": "Pageview ID",
            "description": "PostHog's internal ID for matching events to a pageview.",
        },
        "$autocapture_disabled_server_side": {
            "label": "Autocapture disabled server-side",
            "description": "If autocapture has been disabled server-side.",
        },
        "$console_log_recording_enabled_server_side": {
            "label": "Console log recording enabled server-side",
            "description": "If console log recording has been enabled server-side.",
        },
        "$session_entry__kx": {
            "description": "Klaviyo Tracking ID Captured at the start of the session and remains constant for the duration of the session.",
            "label": "Session entry _kx",
        },
        "$session_entry_dclid": {
            "description": "DoubleClick ID Captured at the start of the session and remains constant for the duration of the session.",
            "label": "Session entry dclid",
        },
        "$session_entry_epik": {
            "description": "Pinterest Click ID Captured at the start of the session and remains constant for the duration of the session.",
            "label": "Session entry epik",
        },
        "$session_entry_fbclid": {
            "description": "Facebook Click ID Captured at the start of the session and remains constant for the duration of the session.",
            "label": "Session entry fbclid",
        },
        "$session_entry_gad_source": {
            "description": "Google Ads Source Captured at the start of the session and remains constant for the duration of the session.",
            "label": "Session entry gad_source",
        },
        "$session_entry_gbraid": {
            "description": "Google Ads, web to app Captured at the start of the session and remains constant for the duration of the session.",
            "label": "Session entry gbraid",
        },
        "$session_entry_gclid": {
            "description": "Google Click ID Captured at the start of the session and remains constant for the duration of the session.",
            "label": "Session entry gclid",
        },
        "$session_entry_gclsrc": {
            "description": "Google Click Source Captured at the start of the session and remains constant for the duration of the session.",
            "label": "Session entry gclsrc",
        },
        "$session_entry_host": {
            "description": "The hostname of the Current URL. Captured at the start of the session and remains constant for the duration of the session.",
            "examples": ["example.com", "localhost:8000"],
            "label": "Session entry Host",
        },
        "$session_entry_igshid": {
            "description": "Instagram Share ID Captured at the start of the session and remains constant for the duration of the session.",
            "label": "Session entry igshid",
        },
        "$session_entry_irclid": {
            "description": "Impact Click ID Captured at the start of the session and remains constant for the duration of the session.",
            "label": "Session entry irclid",
        },
        "$session_entry_li_fat_id": {
            "description": "LinkedIn First-Party Ad Tracking ID Captured at the start of the session and remains constant for the duration of the session.",
            "label": "Session entry li_fat_id",
        },
        "$session_entry_mc_cid": {
            "description": "Mailchimp Campaign ID Captured at the start of the session and remains constant for the duration of the session.",
            "label": "Session entry mc_cid",
        },
        "$session_entry_msclkid": {
            "description": "Microsoft Click ID Captured at the start of the session and remains constant for the duration of the session.",
            "label": "Session entry msclkid",
        },
        "$session_entry_pathname": {
            "description": "The path of the Current URL, which means everything in the url after the domain. Captured at the start of the session and remains constant for the duration of the session.",
            "examples": ["/pricing", "/about-us/team"],
            "label": "Session entry Path name",
        },
        "$session_entry_qclid": {
            "description": "Quora Click ID Captured at the start of the session and remains constant for the duration of the session.",
            "label": "Session entry qclid",
        },
        "$session_entry_rdt_cid": {
            "description": "Reddit Click ID Captured at the start of the session and remains constant for the duration of the session.",
            "label": "Session entry rdt_cid",
        },
        "$session_entry_referrer": {
            "description": "URL of where the user came from. Captured at the start of the session and remains constant for the duration of the session.",
            "examples": ["https://google.com/search?q=posthog&rlz=1C..."],
            "label": "Session entry Referrer URL",
        },
        "$session_entry_referring_domain": {
            "description": "Domain of where the user came from. Captured at the start of the session and remains constant for the duration of the session.",
            "examples": ["google.com", "facebook.com"],
            "label": "Session entry Referring domain",
        },
        "$session_entry_sccid": {
            "description": "Snapchat Click ID Captured at the start of the session and remains constant for the duration of the session.",
            "label": "Session entry sccid",
        },
        "$session_entry_ttclid": {
            "description": "TikTok Click ID Captured at the start of the session and remains constant for the duration of the session.",
            "label": "Session entry ttclid",
        },
        "$session_entry_twclid": {
            "description": "Twitter Click ID Captured at the start of the session and remains constant for the duration of the session.",
            "label": "Session entry twclid",
        },
        "$session_entry_url": {
            "description": "The URL visited at the time of the event. Captured at the start of the session and remains constant for the duration of the session.",
            "examples": ["https://example.com/interesting-article?parameter=true"],
            "label": "Session entry Current URL",
        },
        "$session_entry_utm_campaign": {
            "description": "UTM campaign tag. Captured at the start of the session and remains constant for the duration of the session.",
            "examples": ["feature launch", "discount"],
            "label": "Session entry UTM campaign",
        },
        "$session_entry_utm_content": {
            "description": "UTM content tag. Captured at the start of the session and remains constant for the duration of the session.",
            "examples": ["bottom link", "second button"],
            "label": "Session entry UTM content",
        },
        "$session_entry_utm_medium": {
            "description": "UTM medium tag. Captured at the start of the session and remains constant for the duration of the session.",
            "examples": ["Social", "Organic", "Paid", "Email"],
            "label": "Session entry UTM medium",
        },
        "$session_entry_utm_source": {
            "description": "UTM source tag. Captured at the start of the session and remains constant for the duration of the session.",
            "examples": ["Google", "Bing", "Twitter", "Facebook"],
            "label": "Session entry UTM source",
        },
        "$session_entry_utm_term": {
            "description": "UTM term tag. Captured at the start of the session and remains constant for the duration of the session.",
            "examples": ["free goodies"],
            "label": "Session entry UTM term",
        },
        "$session_entry_wbraid": {
            "description": "Google Ads, app to web Captured at the start of the session and remains constant for the duration of the session.",
            "label": "Session entry wbraid",
        },
        "$session_recording_recorder_version_server_side": {
            "label": "Session recording recorder version server-side",
            "description": "The version of the session recording recorder that is enabled server-side.",
            "examples": ["v2"],
        },
        "$session_is_sampled": {
            "label": "Whether the session is sampled",
            "description": "Whether the session is sampled for session recording.",
            "examples": ["true", "false"],
        },
        "$feature_flag_payloads": {
            "label": "Feature flag payloads",
            "description": "Feature flag payloads active in the environment.",
        },
        "$capture_failed_request": {
            "label": "Capture failed request",
            "description": "",
        },
        "$lib_rate_limit_remaining_tokens": {
            "label": "Clientside rate limit remaining tokens",
            "description": "Remaining rate limit tokens for the posthog-js library client-side rate limiting implementation.",
            "examples": ["100"],
        },
        "token": {
            "label": "Token",
            "description": "Token used for authentication.",
            "examples": ["ph_abcdefg"],
        },
        "$sentry_exception": {
            "label": "Sentry exception",
            "description": "Raw Sentry exception data.",
        },
        "$sentry_exception_message": {
            "label": "Sentry exception message",
        },
        "$sentry_exception_type": {
            "label": "Sentry exception type",
            "description": "Class name of the exception object.",
        },
        "$sentry_tags": {
            "label": "Sentry tags",
            "description": "Tags sent to Sentry along with the exception.",
        },
        "$exception_types": {
            "label": "Exception type",
            "description": "The type of the exception.",
            "examples": ["TypeError"],
        },
        "$exception_functions": {
            "label": "Exception function",
            "description": "A function contained in the exception.",
        },
        "$exception_values": {"label": "Exception message", "description": "The description of the exception."},
        "$exception_sources": {"label": "Exception source", "description": "A source file included in the exception."},
        "$exception_list": {
            "label": "Exception list",
            "description": "List of one or more associated exceptions.",
        },
        "$exception_level": {
            "label": "Exception level",
            "description": "Exception categorized by severity.",
            "examples": ["error"],
        },
        "$exception_type": {
            "label": "Exception type",
            "description": "Exception categorized into types.",
            "examples": ["Error"],
        },
        "$exception_message": {
            "label": "Exception message",
            "description": "The message detected on the error.",
        },
        "$exception_fingerprint": {
            "label": "Exception fingerprint",
            "description": "A fingerprint used to group issues, can be set clientside.",
        },
        "$exception_proposed_fingerprint": {
            "label": "Exception proposed fingerprint",
            "description": "The fingerprint used to group issues. Auto generated unless provided clientside.",
        },
        "$exception_issue_id": {
            "label": "Exception issue ID",
            "description": "The id of the issue the fingerprint was associated with at ingest time.",
        },
        "$exception_source": {
            "label": "Exception source",
            "description": "The source of the exception.",
            "examples": ["JS file"],
        },
        "$exception_lineno": {
            "label": "Exception source line number",
            "description": "Which line in the exception source that caused the exception.",
        },
        "$exception_colno": {
            "label": "Exception source column number",
            "description": "Which column of the line in the exception source that caused the exception.",
        },
        "$exception_DOMException_code": {
            "label": "DOMException code",
            "description": "If a DOMException was thrown, it also has a DOMException code.",
        },
        "$exception_is_synthetic": {
            "label": "Exception is synthetic",
            "description": "Whether this was detected as a synthetic exception.",
        },
        "$exception_handled": {
            "label": "Exception was handled",
            "description": "Whether this was a handled or unhandled exception.",
        },
        "$exception_personURL": {
            "label": "Exception person URL",
            "description": "The PostHog person that experienced the exception.",
        },
        "$cymbal_errors": {
            "label": "Exception processing errors",
            "description": "Errors encountered while trying to process exceptions.",
        },
        "$exception_capture_endpoint": {
            "label": "Exception capture endpoint",
            "description": "Endpoint used by posthog-js exception autocapture.",
            "examples": ["/e/"],
        },
        "$exception_capture_endpoint_suffix": {
            "label": "Exception capture endpoint suffix",
            "description": "Endpoint used by posthog-js exception autocapture.",
            "examples": ["/e/"],
        },
        "$exception_capture_enabled_server_side": {
            "label": "Exception capture enabled server side",
            "description": "Whether exception autocapture was enabled in remote config.",
        },
        "$ce_version": {
            "label": "$ce_version",
            "description": "",
        },
        "$anon_distinct_id": {
            "label": "Anon distinct ID",
            "description": "If the user was previously anonymous, their anonymous ID will be set here.",
            "examples": ["16ff262c4301e5-0aa346c03894bc-39667c0e-1aeaa0-16ff262c431767"],
        },
        "$event_type": {
            "label": "Event type",
            "description": "When the event is an $autocapture event, this specifies what the action was against the element.",
            "examples": ["click", "submit", "change"],
        },
        "$insert_id": {
            "label": "Insert ID",
            "description": "Unique insert ID for the event.",
        },
        "$time": {
            "label": "$time (deprecated)",
            "description": "Use the SQL field `timestamp` instead. This field was previously set on some client side events.",
            "examples": ["1681211521.345"],
        },
        "$browser_type": {
            "label": "Browser type",
            "description": "This is only added when posthog-js config.opt_out_useragent_filter is true.",
            "examples": ["browser", "bot"],
        },
        "$device_id": {
            "label": "Device ID",
            "description": "Unique ID for that device, consistent even if users are logging in/out.",
            "examples": ["16ff262c4301e5-0aa346c03894bc-39667c0e-1aeaa0-16ff262c431767"],
        },
        "$replay_minimum_duration": {
            "label": "Replay config - minimum duration",
            "description": "Config for minimum duration before emitting a session recording.",
            "examples": ["1000"],
        },
        "$replay_sample_rate": {
            "label": "Replay config - sample rate",
            "description": "Config for sampling rate of session recordings.",
            "examples": ["0.1"],
        },
        "$session_recording_start_reason": {
            "label": "Session recording start reason",
            "description": "Reason for starting the session recording. Useful for e.g. if you have sampling enabled and want to see on batch exported events which sessions have recordings available.",
            "examples": ["sampling_override", "recording_initialized", "linked_flag_match"],
        },
        "$session_recording_canvas_recording": {
            "label": "Session recording canvas recording",
            "description": "Session recording canvas capture config.",
            "examples": ['{"enabled": false}'],
        },
        "$session_recording_network_payload_capture": {
            "label": "Session recording network payload capture",
            "description": "Session recording network payload capture config.",
            "examples": ['{"recordHeaders": false}'],
        },
        "$configured_session_timeout_ms": {
            "label": "Configured session timeout",
            "description": "Configured session timeout in milliseconds.",
            "examples": ["1800000"],
        },
        "$replay_script_config": {
            "label": "Replay script config",
            "description": "Sets an alternative recorder script for the web sdk.",
            "examples": ['{"script": "recorder-next"}'],
        },
        "$session_recording_url_trigger_activated_session": {
            "label": "Session recording URL trigger activated session",
            "description": "Session recording URL trigger activated session config. Used by posthog-js to track URL activation of session replay.",
        },
        "$session_recording_url_trigger_status": {
            "label": "Session recording URL trigger status",
            "description": "Session recording URL trigger status. Used by posthog-js to track URL activation of session replay.",
        },
        "$recording_status": {
            "label": "Session recording status",
            "description": "The status of session recording at the time the event was captured",
        },
        "$cymbal_errors": {
            "label": "Exception processing errors",
            "description": "Errors encountered while trying to process exceptions.",
        },
        "$geoip_city_name": {
            "label": "City name",
            "description": "Name of the city matched to this event's IP address.",
            "examples": ["Sydney", "Chennai", "Brooklyn"],
        },
        "$geoip_country_name": {
            "label": "Country name",
            "description": "Name of the country matched to this event's IP address.",
            "examples": ["Australia", "India", "United States"],
        },
        "$geoip_country_code": {
            "label": "Country code",
            "description": "Code of the country matched to this event's IP address.",
            "examples": ["AU", "IN", "US"],
        },
        "$geoip_continent_name": {
            "label": "Continent name",
            "description": "Name of the continent matched to this event's IP address.",
            "examples": ["Oceania", "Asia", "North America"],
        },
        "$geoip_continent_code": {
            "label": "Continent code",
            "description": "Code of the continent matched to this event's IP address.",
            "examples": ["OC", "AS", "NA"],
        },
        "$geoip_postal_code": {
            "label": "Postal code",
            "description": "Approximated postal code matched to this event's IP address.",
            "examples": ["2000", "600004", "11211"],
        },
        "$geoip_postal_code_confidence": {
            "label": "Postal code identification confidence score",
            "description": "If provided by the licensed geoip database",
            "examples": ["null", "0.1"],
        },
        "$geoip_latitude": {
            "label": "Latitude",
            "description": "Approximated latitude matched to this event's IP address.",
            "examples": ["-33.8591", "13.1337", "40.7"],
        },
        "$geoip_longitude": {
            "label": "Longitude",
            "description": "Approximated longitude matched to this event's IP address.",
            "examples": ["151.2", "80.8008", "-73.9"],
        },
        "$geoip_time_zone": {
            "label": "Timezone",
            "description": "Timezone matched to this event's IP address.",
            "examples": ["Australia/Sydney", "Asia/Kolkata", "America/New_York"],
        },
        "$geoip_subdivision_1_name": {
            "label": "Subdivision 1 name",
            "description": "Name of the subdivision matched to this event's IP address.",
            "examples": ["New South Wales", "Tamil Nadu", "New York"],
        },
        "$geoip_subdivision_1_code": {
            "label": "Subdivision 1 code",
            "description": "Code of the subdivision matched to this event's IP address.",
            "examples": ["NSW", "TN", "NY"],
        },
        "$geoip_subdivision_2_name": {
            "label": "Subdivision 2 name",
            "description": "Name of the second subdivision matched to this event's IP address.",
        },
        "$geoip_subdivision_2_code": {
            "label": "Subdivision 2 code",
            "description": "Code of the second subdivision matched to this event's IP address.",
        },
        "$geoip_subdivision_2_confidence": {
            "label": "Subdivision 2 identification confidence score",
            "description": "If provided by the licensed geoip database",
            "examples": ["null", "0.1"],
        },
        "$geoip_subdivision_3_name": {
            "label": "Subdivision 3 name",
            "description": "Name of the third subdivision matched to this event's IP address.",
        },
        "$geoip_subdivision_3_code": {
            "label": "Subdivision 3 code",
            "description": "Code of the third subdivision matched to this event's IP address.",
        },
        "$geoip_disable": {
            "label": "GeoIP disabled",
            "description": "Whether to skip GeoIP processing for the event.",
        },
        "$geoip_city_confidence": {
            "label": "GeoIP detection city confidence",
            "description": "Confidence level of the city matched to this event's IP address.",
            "examples": ["0.5"],
        },
        "$geoip_country_confidence": {
            "label": "GeoIP detection country confidence",
            "description": "Confidence level of the country matched to this event's IP address.",
            "examples": ["0.5"],
        },
        "$geoip_accuracy_radius": {
            "label": "GeoIP detection accuracy radius",
            "description": "Accuracy radius of the location matched to this event's IP address (in kilometers).",
            "examples": ["50"],
        },
        "$geoip_subdivision_1_confidence": {
            "label": "GeoIP detection subdivision 1 confidence",
            "description": "Confidence level of the first subdivision matched to this event's IP address.",
            "examples": ["0.5"],
        },
        "$el_text": {
            "label": "Element text",
            "description": "The text of the element that was clicked. Only sent with Autocapture events.",
            "examples": ["Click here!"],
        },
        "$app_build": {
            "label": "App build",
            "description": "The build number for the app.",
        },
        "$app_name": {
            "label": "App name",
            "description": "The name of the app.",
        },
        "$app_namespace": {
            "label": "App namespace",
            "description": "The namespace of the app as identified in the app store.",
            "examples": ["com.posthog.app"],
        },
        "$app_version": {
            "label": "App version",
            "description": "The version of the app.",
        },
        "$device_manufacturer": {
            "label": "Device manufacturer",
            "description": "The manufacturer of the device",
            "examples": ["Apple", "Samsung"],
        },
        "$device_name": {
            "label": "Device name",
            "description": "Name of the device",
            "examples": ["iPhone 12 Pro", "Samsung Galaxy 10"],
        },
        "$is_emulator": {
            "label": "Is emulator",
            "description": "Indicates whether the app is running on an emulator or a physical device",
            "examples": ["true", "false"],
        },
        "$is_mac_catalyst_app": {
            "label": "Is Mac Catalyst app",
            "description": "Indicates whether the app is a Mac Catalyst app running on macOS",
            "examples": ["true", "false"],
        },
        "$is_ios_running_on_mac": {
            "label": "Is iOS app running on Mac",
            "description": "Indicates whether the app is an iOS app running on macOS (Apple Silicon)",
            "examples": ["true", "false"],
        },
        "$locale": {
            "label": "Locale",
            "description": "The locale of the device",
            "examples": ["en-US", "de-DE"],
        },
        "$os_name": {
            "label": "OS name",
            "description": "The Operating System name",
            "examples": ["iOS", "Android"],
        },
        "$os_version": {
            "label": "OS version",
            "description": "The Operating System version.",
            "examples": ["15.5"],
        },
        "$timezone": {
            "label": "Timezone",
            "description": "The timezone as reported by the device",
        },
        "$timezone_offset": {
            "label": "Timezone offset",
            "description": "The timezone offset, as reported by the device. Minutes difference from UTC.",
            "type": "Numeric",
        },
        "$touch_x": {
            "label": "Touch X",
            "description": "The location of a Touch event on the X axis",
        },
        "$touch_y": {
            "label": "Touch Y",
            "description": "The location of a Touch event on the Y axis",
        },
        "$plugins_succeeded": {
            "label": "Plugins succeeded",
            "description": "Plugins that successfully processed the event, e.g. edited properties (plugin method `processEvent`).",
        },
        "$groups": {
            "label": "Groups",
            "description": "Relevant groups",
        },
        "$group_0": {
            "label": "Group 1",
        },
        "$group_1": {
            "label": "Group 2",
        },
        "$group_2": {
            "label": "Group 3",
        },
        "$group_3": {
            "label": "Group 4",
        },
        "$group_4": {
            "label": "Group 5",
        },
        "$group_set": {
            "label": "Group set",
            "description": "Group properties to be set",
        },
        "$group_key": {
            "label": "Group key",
            "description": "Specified group key",
        },
        "$group_type": {
            "label": "Group type",
            "description": "Specified group type",
        },
        "$window_id": {
            "label": "Window ID",
            "description": "Unique window ID for session recording disambiguation",
        },
        "$session_id": {
            "label": "Session ID",
            "description": "Unique session ID for session recording disambiguation",
        },
        "$plugins_failed": {
            "label": "Plugins failed",
            "description": "Plugins that failed to process the event (plugin method `processEvent`).",
        },
        "$plugins_deferred": {
            "label": "Plugins deferred",
            "description": "Plugins to which the event was handed off post-ingestion, e.g. for export (plugin method `onEvent`).",
        },
        "$$plugin_metrics": {
            "label": "Plugin metric",
            "description": "Performance metrics for a given plugin.",
        },
        "$creator_event_uuid": {
            "label": "Creator event ID",
            "description": "Unique ID for the event, which created this person.",
            "examples": ["16ff262c4301e5-0aa346c03894bc-39667c0e-1aeaa0-16ff262c431767"],
        },
        "utm_source": {
            "label": "UTM source",
            "description": "UTM source tag.",
            "examples": ["Google", "Bing", "Twitter", "Facebook"],
        },
        "$initial_utm_source": {
            "label": "Initial UTM source",
            "description": "UTM source tag.",
            "examples": ["Google", "Bing", "Twitter", "Facebook"],
        },
        "utm_medium": {
            "label": "UTM medium",
            "description": "UTM medium tag.",
            "examples": ["Social", "Organic", "Paid", "Email"],
        },
        "utm_campaign": {
            "label": "UTM campaign",
            "description": "UTM campaign tag.",
            "examples": ["feature launch", "discount"],
        },
        "utm_name": {
            "label": "UTM name",
            "description": "UTM campaign tag, sent via Segment.",
            "examples": ["feature launch", "discount"],
        },
        "utm_content": {
            "label": "UTM content",
            "description": "UTM content tag.",
            "examples": ["bottom link", "second button"],
        },
        "utm_term": {
            "label": "UTM term",
            "description": "UTM term tag.",
            "examples": ["free goodies"],
        },
        "$performance_page_loaded": {
            "label": "Page loaded",
            "description": "The time taken until the browser's page load event in milliseconds.",
        },
        "$performance_raw": {
            "label": "Browser performance",
            "description": "The browser performance entries for navigation (the page), paint, and resources. That were available when the page view event fired",
        },
        "$had_persisted_distinct_id": {
            "label": "$had_persisted_distinct_id",
            "description": "",
        },
        "$sentry_event_id": {
            "label": "Sentry event ID",
            "description": "This is the Sentry key for an event.",
            "examples": ["byroc2ar9ee4ijqp"],
        },
        "$timestamp": {
            "label": "Timestamp (deprecated)",
            "description": "Use the SQL field `timestamp` instead. This field was previously set on some client side events.",
            "examples": ["2023-05-20T15:30:00Z"],
        },
        "$sent_at": {
            "label": "Sent at",
            "description": "Time the event was sent to PostHog. Used for correcting the event timestamp when the device clock is off.",
            "examples": ["2023-05-20T15:31:00Z"],
        },
        "$browser": {
            "label": "Browser",
            "description": "Name of the browser the user has used.",
            "examples": ["Chrome", "Firefox"],
        },
        "$os": {
            "label": "OS",
            "description": "The operating system of the user.",
            "examples": ["Windows", "Mac OS X"],
        },
        "$browser_language": {
            "label": "Browser language",
            "description": "Language.",
            "examples": ["en", "en-US", "cn", "pl-PL"],
        },
        "$browser_language_prefix": {
            "label": "Browser language prefix",
            "description": "Language prefix.",
            "examples": [
                "en",
                "ja",
            ],
        },
        "$current_url": {
            "label": "Current URL",
            "description": "The URL visited at the time of the event.",
            "examples": ["https://example.com/interesting-article?parameter=true"],
        },
        "$browser_version": {
            "label": "Browser version",
            "description": "The version of the browser that was used. Used in combination with Browser.",
            "examples": ["70", "79"],
        },
        "$raw_user_agent": {
            "label": "Raw user agent",
            "description": "PostHog process information like browser, OS, and device type from the user agent string. This is the raw user agent string.",
            "examples": ["Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko)"],
        },
        "$user_agent": {
            "label": "Raw user agent",
            "description": "Some SDKs (like Android) send the raw user agent as $user_agent.",
            "examples": ["Dalvik/2.1.0 (Linux; U; Android 11; Pixel 3 Build/RQ2A.210505.002)"],
        },
        "$screen_height": {
            "label": "Screen height",
            "description": "The height of the user's entire screen (in pixels).",
            "examples": ["2160", "1050"],
        },
        "$screen_width": {
            "label": "Screen width",
            "description": "The width of the user's entire screen (in pixels).",
            "examples": ["1440", "1920"],
        },
        "$screen_name": {
            "label": "Screen name",
            "description": "The name of the active screen.",
        },
        "$viewport_height": {
            "label": "Viewport height",
            "description": "The height of the user's actual browser window (in pixels).",
            "examples": ["2094", "1031"],
        },
        "$viewport_width": {
            "label": "Viewport width",
            "description": "The width of the user's actual browser window (in pixels).",
            "examples": ["1439", "1915"],
        },
        "$lib": {
            "label": "Library",
            "description": "What library was used to send the event.",
            "examples": ["web", "posthog-ios"],
        },
        "$lib_custom_api_host": {
            "label": "Library custom API host",
            "description": "The custom API host used to send the event.",
            "examples": ["https://ph.example.com"],
        },
        "$lib_version": {
            "label": "Library version",
            "description": "Version of the library used to send the event. Used in combination with Library.",
            "examples": ["1.0.3"],
        },
        "$lib_version__major": {
            "label": "Library version (major)",
            "description": "Major version of the library used to send the event.",
            "examples": [1],
        },
        "$lib_version__minor": {
            "label": "Library version (minor)",
            "description": "Minor version of the library used to send the event.",
            "examples": [0],
        },
        "$lib_version__patch": {
            "label": "Library version (patch)",
            "description": "Patch version of the library used to send the event.",
            "examples": [3],
        },
        "$referrer": {
            "label": "Referrer URL",
            "description": "URL of where the user came from.",
            "examples": ["https://google.com/search?q=posthog&rlz=1C..."],
        },
        "$referring_domain": {
            "label": "Referring domain",
            "description": "Domain of where the user came from.",
            "examples": ["google.com", "facebook.com"],
        },
        "$user_id": {
            "label": "User ID",
            "description": "This variable will be set to the distinct ID if you've called `posthog.identify('distinct id')`. If the user is anonymous, it'll be empty.",
        },
        "$ip": {
            "label": "IP address",
            "description": "IP address for this user when the event was sent.",
            "examples": ["203.0.113.0"],
        },
        "$host": {
            "label": "Host",
            "description": "The hostname of the Current URL.",
            "examples": ["example.com", "localhost:8000"],
        },
        "$pathname": {
            "label": "Path name",
            "description": "The path of the Current URL, which means everything in the url after the domain.",
            "examples": ["/pricing", "/about-us/team"],
        },
        "$search_engine": {
            "label": "Search engine",
            "description": "The search engine the user came in from (if any).",
            "examples": ["Google", "DuckDuckGo"],
        },
        "$active_feature_flags": {
            "label": "Active feature flags",
            "description": "Keys of the feature flags that were active while this event was sent.",
            "examples": ["['beta-feature']"],
        },
        "$enabled_feature_flags": {
            "label": "Enabled feature flags",
            "description": "Keys and multivariate values of the feature flags that were active while this event was sent.",
            "examples": ['{"flag": "value"}'],
        },
        "$feature_flag_response": {
            "label": "Feature flag response",
            "description": "What the call to feature flag responded with.",
            "examples": ["true", "false"],
        },
        "$feature_flag_payload": {
            "label": "Feature flag response payload",
            "description": "The JSON payload that the call to feature flag responded with (if any)",
            "examples": ['{"variant": "test"}'],
        },
        "$feature_flag": {
            "label": "Feature flag",
            "description": 'The feature flag that was called.\n\nWarning! This only works in combination with the $feature_flag_called event. If you want to filter other events, try "Active feature flags".',
            "examples": ["beta-feature"],
        },
        "$feature_flag_reason": {
            "label": "Feature flag evaluation reason",
            "description": "The reason the feature flag was matched or not matched.",
            "examples": ["Matched condition set 1"],
        },
        "$feature_flag_request_id": {
            "label": "Feature flag request ID",
            "description": "The unique identifier for the request that retrieved this feature flag result.\n\nNote: Primarily used by PostHog support for debugging issues with feature flags.",
            "examples": ["01234567-89ab-cdef-0123-456789abcdef"],
        },
        "$feature_flag_version": {
            "label": "Feature flag version",
            "description": "The version of the feature flag that was called.",
            "examples": ["3"],
        },
        "$survey_response": {
            "label": "Survey response",
            "description": "The response value for the first question in the survey.",
            "examples": ["I love it!", 5, "['choice 1', 'choice 3']"],
        },
        "$survey_name": {
            "label": "Survey name",
            "description": "The name of the survey.",
            "examples": ["Product Feedback for New Product", "Home page NPS"],
        },
        "$survey_questions": {
            "label": "Survey questions",
            "description": "The questions asked in the survey.",
        },
        "$survey_id": {
            "label": "Survey ID",
            "description": "The unique identifier for the survey.",
        },
        "$survey_iteration": {
            "label": "Survey iteration number",
            "description": "The iteration number for the survey.",
        },
        "$survey_iteration_start_date": {
            "label": "Survey iteration start date",
            "description": "The start date for the current iteration of the survey.",
        },
        "$survey_submission_id": {
            "description": "The unique identifier for the survey submission. Relevant for partial submissions, as they submit multiple 'survey sent' events. This is what allows us to count them as a single submission.",
            "label": "Survey submission ID",
        },
        "$survey_completed": {
            "description": "If a survey was fully completed (all questions answered), this will be true.",
            "label": "Survey completed",
        },
        "$survey_partially_completed": {
            "description": "If a survey was partially completed (some questions answered) on dismissal, this will be true.",
            "label": "Survey partially completed",
        },
        "$device": {
            "label": "Device",
            "description": "The mobile device that was used.",
            "examples": ["iPad", "iPhone", "Android"],
        },
        "$sentry_url": {
            "label": "Sentry URL",
            "description": "Direct link to the exception in Sentry",
            "examples": ["https://sentry.io/..."],
        },
        "$device_type": {
            "label": "Device type",
            "description": "The type of device that was used.",
            "examples": ["Mobile", "Tablet", "Desktop"],
        },
        "$screen_density": {
            "label": "Screen density",
            "description": 'The logical density of the display. This is a scaling factor for the Density Independent Pixel unit, where one DIP is one pixel on an approximately 160 dpi screen (for example a 240x320, 1.5"x2" screen), providing the baseline of the system\'s display. Thus on a 160dpi screen this density value will be 1; on a 120 dpi screen it would be .75; etc.',
            "examples": [2.75],
        },
        "$device_model": {
            "label": "Device model",
            "description": "The model of the device that was used.",
            "examples": ["iPhone9,3", "SM-G965W"],
        },
        "$network_wifi": {
            "label": "Network WiFi",
            "description": "Whether the user was on WiFi when the event was sent.",
            "examples": ["true", "false"],
        },
        "$network_bluetooth": {
            "label": "Network Bluetooth",
            "description": "Whether the user was on Bluetooth when the event was sent.",
            "examples": ["true", "false"],
        },
        "$network_cellular": {
            "label": "Network Cellular",
            "description": "Whether the user was on cellular when the event was sent.",
            "examples": ["true", "false"],
        },
        "$client_session_initial_referring_host": {
            "label": "Referrer host",
            "description": "Host that the user came from. (First-touch, session-scoped)",
            "examples": ["google.com", "facebook.com"],
        },
        "$client_session_initial_pathname": {
            "label": "Initial path",
            "description": "Path that the user started their session on. (First-touch, session-scoped)",
            "examples": ["/register", "/some/landing/page"],
        },
        "$client_session_initial_utm_source": {
            "label": "Initial UTM source",
            "description": "UTM Source. (First-touch, session-scoped)",
            "examples": ["Google", "Bing", "Twitter", "Facebook"],
        },
        "$client_session_initial_utm_campaign": {
            "label": "Initial UTM campaign",
            "description": "UTM Campaign. (First-touch, session-scoped)",
            "examples": ["feature launch", "discount"],
        },
        "$client_session_initial_utm_medium": {
            "label": "Initial UTM medium",
            "description": "UTM Medium. (First-touch, session-scoped)",
            "examples": ["Social", "Organic", "Paid", "Email"],
        },
        "$client_session_initial_utm_content": {
            "label": "Initial UTM source",
            "description": "UTM Source. (First-touch, session-scoped)",
            "examples": ["bottom link", "second button"],
        },
        "$client_session_initial_utm_term": {
            "label": "Initial UTM term",
            "description": "UTM term. (First-touch, session-scoped)",
            "examples": ["free goodies"],
        },
        "$network_carrier": {
            "label": "Network carrier",
            "description": "The network carrier that the user is on.",
            "examples": ["cricket", "telecom"],
        },
        "from_background": {
            "label": "From background",
            "description": "Whether the app was opened for the first time or from the background.",
            "examples": ["true", "false"],
        },
        "url": {
            "label": "URL",
            "description": "The deep link URL that the app was opened from.",
            "examples": ["https://open.my.app"],
        },
        "referring_application": {
            "label": "Referrer application",
            "description": "The namespace of the app that made the request.",
            "examples": ["com.posthog.app"],
        },
        "version": {
            "label": "App version",
            "description": "The version of the app",
            "examples": ["1.0.0"],
        },
        "previous_version": {
            "label": "App previous version",
            "description": "The previous version of the app",
            "examples": ["1.0.0"],
        },
        "build": {
            "label": "App build",
            "description": "The build number for the app",
            "examples": ["1"],
        },
        "previous_build": {
            "label": "App previous build",
            "description": "The previous build number for the app",
            "examples": ["1"],
        },
        "gclid": {
            "label": "gclid",
            "description": "Google Click ID",
        },
        "rdt_cid": {
            "label": "rdt_cid",
            "description": "Reddit Click ID",
        },
        "epik": {
            "label": "epik",
            "description": "Pinterest Click ID",
        },
        "qclid": {
            "label": "qclid",
            "description": "Quora Click ID",
        },
        "sccid": {
            "label": "sccid",
            "description": "Snapchat Click ID",
        },
        "irclid": {
            "label": "irclid",
            "description": "Impact Click ID",
        },
        "_kx": {
            "label": "_kx",
            "description": "Klaviyo Tracking ID",
        },
        "gad_source": {
            "label": "gad_source",
            "description": "Google Ads Source",
        },
        "gclsrc": {
            "label": "gclsrc",
            "description": "Google Click Source",
        },
        "dclid": {
            "label": "dclid",
            "description": "DoubleClick ID",
        },
        "gbraid": {
            "label": "gbraid",
            "description": "Google Ads, web to app",
        },
        "wbraid": {
            "label": "wbraid",
            "description": "Google Ads, app to web",
        },
        "fbclid": {
            "label": "fbclid",
            "description": "Facebook Click ID",
        },
        "msclkid": {
            "label": "msclkid",
            "description": "Microsoft Click ID",
        },
        "twclid": {
            "label": "twclid",
            "description": "Twitter Click ID",
        },
        "li_fat_id": {
            "label": "li_fat_id",
            "description": "LinkedIn First-Party Ad Tracking ID",
        },
        "mc_cid": {
            "label": "mc_cid",
            "description": "Mailchimp Campaign ID",
        },
        "igshid": {
            "label": "igshid",
            "description": "Instagram Share ID",
        },
        "ttclid": {
            "label": "ttclid",
            "description": "TikTok Click ID",
        },
        "$is_identified": {
            "label": "Is identified",
            "description": "When the person was identified",
        },
        "$initial_person_info": {
            "label": "Initial person info",
            "description": "posthog-js initial person information. used in the $set_once flow",
            "system": True,
        },
        "revenue": {
            "label": "Revenue",
            "description": "The revenue associated with the event. By default, this is in USD, but the currency property can be used to specify a different currency.",
            "examples": [10.0],
        },
        "currency": {
            "label": "Currency",
            "description": "The currency code associated with the event.",
            "examples": ["USD", "EUR", "GBP", "CAD"],
        },
        "$web_vitals_enabled_server_side": {
            "label": "Web vitals enabled server side",
            "description": "Whether web vitals was enabled in remote config",
        },
        "$web_vitals_FCP_event": {
            "label": "Web vitals FCP measure event details",
        },
        "$web_vitals_FCP_value": {
            "label": "Web vitals FCP value",
        },
        "$web_vitals_LCP_event": {
            "label": "Web vitals LCP measure event details",
        },
        "$web_vitals_LCP_value": {
            "label": "Web vitals LCP value",
        },
        "$web_vitals_INP_event": {
            "label": "Web vitals INP measure event details",
        },
        "$web_vitals_INP_value": {
            "label": "Web vitals INP value",
        },
        "$web_vitals_CLS_event": {
            "label": "Web vitals CLS measure event details",
        },
        "$web_vitals_CLS_value": {
            "label": "Web vitals CLS value",
        },
        "$web_vitals_allowed_metrics": {
            "label": "Web vitals allowed metrics",
            "description": "Allowed web vitals metrics config.",
            "examples": ['["LCP", "CLS"]'],
            "system": True,
        },
        "$prev_pageview_last_scroll": {
            "label": "Previous pageview last scroll",
            "description": "posthog-js adds these to the page leave event, they are used in web analytics calculations",
            "examples": [0],
        },
        "$prev_pageview_id": {
            "label": "Previous pageview ID",
            "description": "posthog-js adds these to the page leave event, they are used in web analytics calculations",
            "examples": ["1"],
            "system": True,
        },
        "$prev_pageview_last_scroll_percentage": {
            "label": "Previous pageview last scroll percentage",
            "description": "posthog-js adds these to the page leave event, they are used in web analytics calculations",
            "examples": [0],
        },
        "$prev_pageview_max_scroll": {
            "examples": [0],
            "label": "Previous pageview max scroll",
            "description": "posthog-js adds these to the page leave event, they are used in web analytics calculations",
        },
        "$prev_pageview_max_scroll_percentage": {
            "examples": [0],
            "label": "Previous pageview max scroll percentage",
            "description": "posthog-js adds these to the page leave event, they are used in web analytics calculations",
        },
        "$prev_pageview_last_content": {
            "examples": [0],
            "description": "posthog-js adds these to the page leave event, they are used in web analytics calculations",
            "label": "Previous pageview last content",
        },
        "$prev_pageview_last_content_percentage": {
            "examples": [0],
            "description": "posthog-js adds these to the page leave event, they are used in web analytics calculations",
            "label": "Previous pageview last content percentage",
        },
        "$prev_pageview_max_content": {
            "examples": [0],
            "description": "posthog-js adds these to the page leave event, they are used in web analytics calculations",
            "label": "Previous pageview max content",
        },
        "$prev_pageview_max_content_percentage": {
            "examples": [0],
            "description": "posthog-js adds these to the page leave event, they are used in web analytics calculations",
            "label": "Previous pageview max content percentage",
        },
        "$prev_pageview_pathname": {
            "examples": ["/pricing", "/about-us/team"],
            "description": "posthog-js adds these to the page leave event, they are used in web analytics calculations",
            "label": "Previous pageview pathname",
        },
        "$prev_pageview_duration": {
            "examples": [0],
            "description": "posthog-js adds these to the page leave event, they are used in web analytics calculations",
            "label": "Previous pageview duration",
        },
        "$surveys_activated": {
            "label": "Surveys activated",
            "description": "The surveys that were activated for this event.",
        },
        "$process_person_profile": {
            "label": "Person profile processing flag",
            "description": "The setting from an SDK to control whether an event has person processing enabled",
            "system": True,
        },
        "$dead_clicks_enabled_server_side": {
            "label": "Dead clicks enabled server side",
            "description": "Whether dead clicks were enabled in remote config",
            "system": True,
        },
        "$dead_click_scroll_delay_ms": {
            "label": "Dead click scroll delay in milliseconds",
            "description": "The delay between a click and the next scroll event",
            "system": True,
        },
        "$dead_click_mutation_delay_ms": {
            "label": "Dead click mutation delay in milliseconds",
            "description": "The delay between a click and the next mutation event",
            "system": True,
        },
        "$dead_click_absolute_delay_ms": {
            "label": "Dead click absolute delay in milliseconds",
            "description": "The delay between a click and having seen no activity at all",
            "system": True,
        },
        "$dead_click_selection_changed_delay_ms": {
            "label": "Dead click selection changed delay in milliseconds",
            "description": "The delay between a click and the next text selection change event",
            "system": True,
        },
        "$dead_click_last_mutation_timestamp": {
            "label": "Dead click last mutation timestamp",
            "description": "debug signal time of the last mutation seen by dead click autocapture",
            "system": True,
        },
        "$dead_click_event_timestamp": {
            "label": "Dead click event timestamp",
            "description": "debug signal time of the event that triggered dead click autocapture",
            "system": True,
        },
        "$dead_click_scroll_timeout": {
            "label": "Dead click scroll timeout",
            "description": "whether the dead click autocapture passed the threshold for waiting for a scroll event",
        },
        "$dead_click_mutation_timeout": {
            "label": "Dead click mutation timeout",
            "description": "whether the dead click autocapture passed the threshold for waiting for a mutation event",
            "system": True,
        },
        "$dead_click_absolute_timeout": {
            "label": "Dead click absolute timeout",
            "description": "whether the dead click autocapture passed the threshold for waiting for any activity",
            "system": True,
        },
        "$dead_click_selection_changed_timeout": {
            "label": "Dead click selection changed timeout",
            "description": "whether the dead click autocapture passed the threshold for waiting for a text selection change event",
            "system": True,
        },
        # AI
        "$ai_base_url": {
            "label": "AI base URL (LLM)",
            "description": "The base URL of the request made to the LLM API.",
            "examples": ["https://api.openai.com/v1/"],
        },
        "$ai_http_status": {
            "label": "AI HTTP status (LLM)",
            "description": "The HTTP status code of the request made to the LLM API.",
            "examples": [200, 429],
        },
        "$ai_input": {
            "label": "AI input (LLM)",
            "description": "The input JSON that was sent to the LLM API.",
            "examples": ['{"content": "Explain quantum computing in simple terms.", "role": "user"}'],
        },
        "$ai_input_tokens": {
            "label": "AI input tokens (LLM)",
            "description": "The number of tokens in the input prompt that was sent to the LLM API.",
            "examples": [23],
        },
        "$ai_output_choices": {
            "label": "AI output (LLM)",
            "description": "The output message choices JSON that was received from the LLM API.",
            "examples": [
                '{"choices": [{"text": "Quantum computing is a type of computing that harnesses the power of quantum mechanics to perform operations on data."}]}',
            ],
        },
        "$ai_output_tokens": {
            "label": "AI output tokens (LLM)",
            "description": "The number of tokens in the output from the LLM API.",
            "examples": [23],
        },
        "$ai_cache_read_input_tokens": {
            "label": "AI cache read input tokens (LLM)",
            "description": "The number of tokens read from the cache for the input prompt.",
            "examples": [23],
        },
        "$ai_cache_creation_input_tokens": {
            "label": "AI cache creation input tokens (LLM)",
            "description": "The number of tokens created in the cache for the input prompt (anthropic only).",
            "examples": [23],
        },
        "$ai_reasoning_tokens": {
            "label": "AI reasoning tokens (LLM)",
            "description": "The number of tokens in the reasoning output from the LLM API.",
            "examples": [23],
        },
        "$ai_input_cost_usd": {
            "label": "AI input cost USD (LLM)",
            "description": "The cost in USD of the input tokens sent to the LLM API.",
            "examples": [0.0017],
        },
        "$ai_output_cost_usd": {
            "label": "AI output cost USD (LLM)",
            "description": "The cost in USD of the output tokens received from the LLM API.",
            "examples": [0.0024],
        },
        "$ai_total_cost_usd": {
            "label": "AI total cost USD (LLM)",
            "description": "The total cost in USD of the request made to the LLM API (input + output costs).",
            "examples": [0.0041],
        },
        "$ai_latency": {
            "label": "AI latency (LLM)",
            "description": "The latency of the request made to the LLM API, in seconds.",
            "examples": [0.361],
        },
        "$ai_model": {
            "label": "AI model (LLM)",
            "description": "The model used to generate the output from the LLM API.",
            "examples": ["gpt-4o-mini"],
        },
        "$ai_model_parameters": {
            "label": "AI model parameters (LLM)",
            "description": "The parameters used to configure the model in the LLM API, in JSON.",
            "examples": ['{"temperature": 0.5, "max_tokens": 50}'],
        },
        "$ai_tools": {
            "label": "AI tools (LLM)",
            "description": "The tools available to the LLM.",
            "examples": [
                '[{"type": "function", "function": {"name": "tool1", "arguments": {"arg1": "value1", "arg2": "value2"}}}]',
            ],
        },
        "$ai_stream": {
            "label": "AI stream (LLM)",
            "description": "Whether the response from the LLM API was streamed.",
            "examples": ["true", "false"],
        },
        "$ai_temperature": {
            "label": "AI temperature (LLM)",
            "description": "The temperature parameter used in the request to the LLM API.",
            "examples": [0.7, 1.0],
        },
        "$ai_input_state": {
            "label": "AI Input State (LLM)",
            "description": "Input state of the LLM agent.",
        },
        "$ai_output_state": {
            "label": "AI Output State (LLM)",
            "description": "Output state of the LLM agent.",
        },
        "$ai_provider": {
            "label": "AI Provider (LLM)",
            "description": "The provider of the AI model used to generate the output from the LLM API.",
            "examples": ["openai"],
        },
        "$ai_trace_id": {
            "label": "AI Trace ID (LLM)",
            "description": "The trace ID of the request made to the LLM API. Used to group together multiple generations into a single trace.",
            "examples": ["c9222e05-8708-41b8-98ea-d4a21849e761"],
        },
        "$ai_request_url": {
            "label": "AI Request URL (LLM)",
            "description": "The full URL of the request made to the LLM API.",
            "examples": ["https://api.openai.com/v1/chat/completions"],
        },
        "$ai_metric_name": {
            "label": "AI Metric Name (LLM)",
            "description": "The name assigned to the metric used to evaluate the LLM trace.",
            "examples": ["rating", "accuracy"],
        },
        "$ai_metric_value": {
            "label": "AI Metric Value (LLM)",
            "description": "The value assigned to the metric used to evaluate the LLM trace.",
            "examples": ["negative", "95"],
        },
        "$ai_feedback_text": {
            "label": "AI Feedback Text (LLM)",
            "description": "The text provided by the user for feedback on the LLM trace.",
            "examples": ['"The response was helpful, but it did not use the provided context."'],
        },
        "$ai_parent_id": {
            "label": "AI Parent ID (LLM)",
            "description": "The parent span ID of a span or generation, used to group a trace into a tree view.",
            "examples": ["bdf42359-9364-4db7-8958-c001f28c9255"],
        },
        "$ai_span_id": {
            "label": "AI Span ID (LLM)",
            "description": "The unique identifier for a LLM trace, generation, or span.",
            "examples": ["bdf42359-9364-4db7-8958-c001f28c9255"],
        },
        "$ai_span_name": {
            "label": "AI Span Name (LLM)",
            "description": "The name given to this LLM trace, generation, or span.",
            "examples": ["summarize_text"],
        },
        "$csp_document_url": {
            "label": "Document URL",
            "description": "The URL of the document where the violation occurred.",
            "examples": ["https://example.com/page"],
        },
        "$csp_violated_directive": {
            "label": "Violated directive",
            "description": "The CSP directive that was violated.",
            "examples": ["script-src", "img-src", "default-src"],
        },
        "$csp_effective_directive": {
            "label": "Effective directive",
            "description": "The CSP directive that was effectively violated.",
            "examples": ["script-src", "img-src", "default-src"],
        },
        "$csp_original_policy": {
            "label": "Original policy",
            "description": "The CSP policy that was active when the violation occurred.",
            "examples": ["default-src 'self'; script-src 'self' example.com"],
        },
        "$csp_disposition": {
            "label": "Disposition",
            "description": "The disposition of the CSP policy that was violated (enforce or report).",
            "examples": ["enforce", "report"],
        },
        "$csp_blocked_url": {
            "label": "Blocked URL",
            "description": "The URL that was blocked by the CSP policy.",
            "examples": ["https://malicious-site.com/script.js"],
        },
        "$csp_line_number": {
            "label": "Line number",
            "description": "The line number in the source file where the violation occurred.",
            "examples": ["42"],
        },
        "$csp_column_number": {
            "label": "Column number",
            "description": "The column number in the source file where the violation occurred.",
            "examples": ["13"],
        },
        "$csp_source_file": {
            "label": "Source file",
            "description": "The source file where the violation occurred.",
            "examples": ["script.js"],
        },
        "$csp_status_code": {
            "label": "Status code",
            "description": "The HTTP status code that was returned when trying to load the blocked resource.",
            "examples": ["200", "404"],
        },
        "$csp_script_sample": {
            "label": "Script sample",
            "description": "An escaped sample of the script that caused the violation. Usually capped at 40 characters.",
            "examples": ["eval('alert(1)')"],
        },
        "$csp_report_type": {
            "label": "Report type",
            "description": "The type of CSP report.",
        },
        "$csp_raw_report": {
            "label": "Raw CSP report",
            "description": "The raw CSP report as received from the browser.",
        },
        "$csp_referrer": {
            "label": "CSP Referrer",
            "description": "The referrer of the CSP report if available.",
            "examples": ["https://example.com/referrer"],
        },
        "$csp_version": {
            "label": "CSP Policy version",
            "description": "The version of the CSP policy. Must be provided in the report URL.",
            "examples": ["1.0"],
        },
    }
"""
PERSON_TAXONOMY_MESSAGE = """
Here is the taxonomy for person properties:
"person_properties": {
        "email": {
            "label": "Email address",
            "description": "The email address of the user.",
            "examples": ["johnny.appleseed@icloud.com", "sales@posthog.com", "test@example.com"],
            "type": "String",
        },
        "$virt_initial_channel_type": {
            "description": "What type of acquisition channel this user initially came from. Learn more about channels types and how to customise them in [our documentation](https://posthog.com/docs/data/channel-type)",
            "examples": ["Paid Search", "Organic Video", "Direct"],
            "label": "Initial channel type",
            "type": "String",
            "virtual": True,
        },
        "$virt_initial_referring_domain_type": {
            "description": "What type of referring domain this user initially came from.",
            "examples": ["Search", "Video", "Direct"],
            "label": "Initial referring domain type",
            "type": "String",
            "virtual": True,
        },
    }
"""

FILTER_TAXONOMY_MESSAGE = """
Here is the taxonomy for event properties:
PROPERTY_FILTER_VERBOSE_NAME: dict[PropertyOperator, str] = {
    PropertyOperator.EXACT: "matches exactly",
    PropertyOperator.IS_NOT: "is not",
    PropertyOperator.ICONTAINS: "contains",
    PropertyOperator.NOT_ICONTAINS: "doesn't contain",
    PropertyOperator.REGEX: "matches regex",
    PropertyOperator.NOT_REGEX: "doesn't match regex",
    PropertyOperator.GT: "greater than",
    PropertyOperator.GTE: "greater than or equal to",
    PropertyOperator.LT: "less than",
    PropertyOperator.LTE: "less than or equal to",
    PropertyOperator.IS_SET: "is set",
    PropertyOperator.IS_NOT_SET: "is not set",
    PropertyOperator.IS_DATE_EXACT: "is on exact date",
    PropertyOperator.IS_DATE_BEFORE: "is before date",
    PropertyOperator.IS_DATE_AFTER: "is after date",
    PropertyOperator.BETWEEN: "is between",
    PropertyOperator.NOT_BETWEEN: "is not between",
    PropertyOperator.MIN: "is a minimum value",
    PropertyOperator.MAX: "is a maximum value",
    PropertyOperator.IN_: "is one of the values in",
    PropertyOperator.NOT_IN: "is not one of the values in",
    PropertyOperator.IS_CLEANED_PATH_EXACT: "has a link without a hash and URL parameters that matches exactly",
}
"""

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

Common operators:
- "exact" for exact matches
- "icontains" for contains
- "regex" for regex patterns
- "gt", "lt", "gte", "lte" for numeric comparisons

Return ONLY the JSON object inside <filters> tags. Do not add any other text or explanation."""

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
