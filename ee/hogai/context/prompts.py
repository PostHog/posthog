ROOT_UI_CONTEXT_PROMPT = """
<attached_context>
{{{ui_context_dashboard}}}
{{{ui_context_insights}}}
{{{ui_context_notebooks}}}
{{{ui_context_events}}}
{{{ui_context_actions}}}
{{{ui_context_error_tracking}}}
{{{ui_context_evaluations}}}
</attached_context>
<system_reminder>
The user can provide additional context in the <attached_context> tag.
If the user's request is ambiguous, use the context to direct your answer as much as possible.
If the user's provided context has nothing to do with previous interactions, ignore any past interaction and use this new context instead. The user probably wants to change topic.
You can acknowledge that you are using this context to answer the user's request.
</system_reminder>
""".strip()

ROOT_DASHBOARDS_CONTEXT_PROMPT = """
# Dashboards
The user has provided the following dashboards.

{{{dashboards}}}
""".strip()

ROOT_DASHBOARD_CONTEXT_PROMPT = """
## {{{content}}}
""".strip()

ROOT_INSIGHTS_CONTEXT_PROMPT = """
# Insights
The user has provided the following insights, which may be relevant to the question at hand:
{{{insights}}}
""".strip()

ROOT_INSIGHT_CONTEXT_PROMPT = """
{{{heading}}} {{{insight_prompt}}}
""".strip()

CONTEXTUAL_TOOLS_REMINDER_PROMPT = """
<system_reminder>
Contextual tools that are available to you on this page are:
{tools}
IMPORTANT: this context may or may not be relevant to your tasks. You should not respond to this context unless it is highly relevant to your task.
</system_reminder>
""".strip()

HOG_EVALUATION_REFERENCE = """
Hog language reference for writing evaluations:

Available globals:
- `input`: LLM prompt/messages as a string (may be JSON — use `jsonParse(input)` to parse)
- `output`: LLM response as a string (may be JSON — use `jsonParse(output)` to parse)
- `properties`: all event properties (e.g. `properties.$ai_model`, `properties.$ai_total_cost_usd`, `properties.$ai_latency`, `properties.$ai_total_tokens`)
- `event`: object with `uuid`, `event`, `distinct_id` fields

Return type: boolean — `true` (pass) or `false` (fail)
When "Allow N/A responses" is enabled on the evaluation, `return null` means "not applicable" (the evaluation criteria doesn't apply to this event).
Use `print('...')` to add reasoning visible in evaluation results.

When generating Hog code, use comments liberally (`//`) to explain what each section does and why.
Many users are learning Hog for the first time, so the generated code should be educational and easy to follow.

Syntax essentials:
- Strings use SINGLE quotes: `'hello'` (not double quotes)
- Assignment: `let x := 1` (use `:=`, not `=`)
- No ternary operator — use `if/else` blocks
- Comments: `//`, `--`, or `/* ... */`
- Define functions: `fun myFunc(a, b) { return a + b }`
- Lambdas: `let f := (x) -> x + 1`
- For loops: `for (let i, item in array) { ... }`
- Arrays/tuples are 1-indexed: `let a := [1,2,3]; print(a[1])` prints 1
- Objects use single-quoted keys: `let o := {'key': 'value'}`
- `null` is the null/missing value (used for N/A returns when enabled)

CRITICAL — null handling (properties can be null!):
- `ifNull(value, default)`: returns default if value is null
- `coalesce(a, b, c)`: returns first non-null value
- ALWAYS use `ifNull()` when accessing properties before comparing: `if (ifNull(properties.$ai_latency, 0) > 10)` — without this, comparing null > number throws a runtime error

Standard library — strings:
- `length(s)`, `empty(s)`, `notEmpty(s)` — length and emptiness checks (NOT `len()`)
- `lower(s)`, `upper(s)`, `trim(s)`, `reverse(s)`
- `concat(a, b, ...)` — concatenate strings
- `substring(s, start, length)` — extract substring (1-indexed)
- `replaceOne(s, needle, replacement)`, `replaceAll(s, needle, replacement)`
- `splitByString(sep, s)` — split into array
- `startsWith(s, prefix)`, `endsWith(s, suffix)`
- `like`, `ilike`, `not like`, `not ilike` — SQL-style pattern matching (% and _)
- `=~` (regex match), `!~` (regex not match), `=~*` / `!~*` (case-insensitive)
- `match(s, pattern)` — regex match function

Standard library — arrays:
- `length(arr)`, `empty(arr)`
- `arrayPushBack(arr, item)`, `arrayPushFront(arr, item)`
- `arrayPopBack(arr)`, `arrayPopFront(arr)`
- `has(arr, item)` — check if array contains item
- `arraySort(arr)`, `arrayReverse(arr)`
- `arrayMap(fn, arr)`, `arrayFilter(fn, arr)` — functional operations
- `arrayCount(fn, arr)` — count matching elements

Standard library — type & conversion:
- `toString(x)`, `toInt(x)`, `toFloat(x)`
- `typeof(x)` — returns 'string', 'integer', 'float', 'boolean', 'array', 'object', 'null'
- `jsonParse(s)` — parse JSON string to object/array
- `jsonStringify(x)` — serialize to JSON string

Standard library — other:
- `ifNull(value, default)`, `coalesce(a, b, ...)`
- `now()`, `toUnixTimestamp(dt)`, `fromUnixTimestamp(n)`
- `generateUUIDv4()`

Example patterns for evaluations:
- Output not empty: `return length(output) > 0`
- Min length check: `return length(output) >= 100`
- Keyword matching: loop over keywords array, use `output ilike concat('%', kw, '%')`
- Cost/latency guard: `ifNull(properties.$ai_total_cost_usd, 0) > threshold`
- Refusal detection: check for phrases like 'I cannot', 'I\\'m unable' via `ilike`
- Error detection: split output by newlines, check each line for error patterns
- Regex safety: use `output =~ 'pattern'` to detect emails, URLs, phone numbers
- Parse messages: `let msgs := jsonParse(input); for (let i, msg in msgs) { ... }`
- Conversation length: parse input messages array, check `length(messages) <= max`
- Input relevance: extract key terms from input, check they appear in output

Example — cost guard with null safety:
```hog
let cost := ifNull(properties.$ai_total_cost_usd, 0)
let latency := ifNull(properties.$ai_latency, 0)
if (cost > 0.05) {
    print(concat('Cost $', toString(cost), ' exceeds budget'))
    return false
}
if (latency > 10) {
    print(concat('Latency ', toString(latency), 's too high'))
    return false
}
return true
```
""".strip()

CONTEXT_INITIAL_MODE_PROMPT = "Your initial mode is"
CONTEXT_MODE_SWITCH_PROMPT = "Your mode has been switched to"
CONTEXT_MODE_PROMPT = """
<system_reminder>{{{mode_prompt}}} {{{mode}}}.</system_reminder>
""".strip()
