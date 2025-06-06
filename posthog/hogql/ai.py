import os
from typing import TYPE_CHECKING, Optional
import posthoganalytics
from posthoganalytics.ai.openai import OpenAI
import openai
from posthog.event_usage import report_user_action
from posthog.hogql.context import HogQLContext
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import print_ast
from .database.database import create_hogql_database, serialize_database
from posthog.utils import get_instance_region
from .query import create_default_modifiers_for_team

if TYPE_CHECKING:
    from posthog.models import User, Team

openai_client = OpenAI(posthog_client=posthoganalytics) if os.getenv("OPENAI_API_KEY") else None  # type: ignore

UNCLEAR_PREFIX = "UNCLEAR:"

IDENTITY_MESSAGE = """HogQL is PostHog's variant of SQL. It supports most of ClickHouse SQL. You write HogQL based on a prompt. You don't help with other knowledge.

Clickhouse DOES NOT support the following functions:
- LAG/LEAD

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

Important HogQL differences versus other SQL dialects:
- JSON properties are accessed like `properties.foo.bar` instead of `properties->foo->bar`
"""

SCHEMA_MESSAGE = """
This project's schema is:

{schema_description}

Person or event metadata unspecified above (emails, names, etc.) is stored in `properties` fields, accessed like: `properties.foo.bar`.
Note: "persons" means "users" here - instead of a "users" table, we have a "persons" table.

Standardized events/properties such as pageview or screen start with `$`. Custom events/properties start with any other character.

`virtual_table` and `lazy_table` fields are connections to linked tables, e.g. the virtual table field `person` allows accessing person properties like so: `person.properties.foo`.
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
    database = create_hogql_database(team=team)
    context = HogQLContext(
        team_id=team.pk,
        enable_select_queries=True,
        database=database,
        modifiers=create_default_modifiers_for_team(team),
    )
    serialized_database = serialize_database(context)
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
            print_ast(parse_select(candidate_sql), context=context, dialect="clickhouse")
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
        model="gpt-4o-mini",
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

    try {
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

return returnEvent

"""

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

"""


