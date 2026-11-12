"""Agent-aware Hog checks, filled with one team's tool names and error classes before they are measured.

The catalog's Hog templates are written as examples. Run as they are, they fail most traces of a real
agent: they count approval pauses as errors, flag URLs as sensitive data, and treat a dispatcher tool
called many times as a loop. These versions check the final result of a trace instead.
"""

import re
from collections.abc import Iterable, Sequence

from posthog.dataclasses import frozen

from products.ai_observability.backend.hog import compile_ai_observability_hog

UNRECOVERED_ERRORS = "unrecovered_errors"
REPEATED_TOOL_CALLS = "repeated_tool_calls"
REFUSALS = "refusals"
SENSITIVE_DATA = "sensitive_data"

# Error messages that mean "paused" or "stopped on purpose" in common agent frameworks.
DEFAULT_IGNORED_ERROR_PREFIXES: tuple[str, ...] = (
    "GraphInterrupt",
    "NodeInterrupt",
    "CancelledError",
    "GenerationCanceled",
    "GeneratorExit",
    "context canceled",
)
# Whole words or a class-name suffix, so a real failure that only mentions one (`Connection aborted.`,
# `ApprovalServiceError: 503`) still counts.
PAUSE_ERROR_PATTERN = re.compile(
    r"(?i:\b(paused|cancell?ed|interrupted|awaiting approval|approval (required|pending))\b)|Interrupt\b|Cancell?edError\b"
)
POLLING_TOOL_PATTERN = re.compile(r"(^|[_.\-])(poll|wait|sleep|status|heartbeat|progress)([_.\-]|$)", re.IGNORECASE)
REPEAT_THRESHOLD = 3

# A refusal is an opener followed by what the assistant won't do, so "I'm unable to find a bug" is not one.
REFUSAL_OPENERS: tuple[str, ...] = (
    "i can't",
    "i cannot",
    "i'm unable to",
    "i am unable to",
    "i'm not able to",
    "i am not able to",
    "i won't be able to",
)
REFUSAL_ACTIONS = "help|assist|do that|share|provide|comply|answer|fulfill|complete|give"
# Placeholder domains that documentation and test data use, so an address on them leaks nothing.
IGNORED_EMAIL_DOMAINS: tuple[str, ...] = ("example.com", "example.org", "example.net", "test.com", "localhost")


@frozen
class AdaptedCheck:
    key: str
    name: str
    description: str
    source: str
    # Catalog template this check replaces in the UI, or "" when the catalog has no such template.
    template_key: str
    severity: float


def hog_string(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def hog_list(values: Iterable[str]) -> str:
    return "[" + ", ".join(hog_string(value) for value in values) + "]"


# Every tool call in a parsed output, as [tool, arguments, call id]. An empty `tool_calls` list holds none.
_COLLECT_CALLS = """fun collect_calls(value, calls) {
    let kind := typeof(value)
    if (kind == 'array') {
        for (let i, child in value) {
            calls := collect_calls(child, calls)
        }
        return calls
    }
    if (kind != 'object') {
        return calls
    }
    if (typeof(value.function) == 'object') {
        if (value.function.name != null) {
            let id := toString(ifNull(value.id, ''))
            return arrayPushBack(calls, [toString(value.function.name), jsonStringify(value.function.arguments), id])
        }
    }
    if (has(['tool_use', 'function_call', 'tool-call', 'tool_call'], toString(value.type))) {
        let tool := ifNull(value.toolName, value.name)
        if (tool != null) {
            let id := toString(ifNull(value.id, ifNull(value.call_id, ifNull(value.toolCallId, ''))))
            return arrayPushBack(calls, [toString(tool), jsonStringify(ifNull(value.arguments, value.input)), id])
        }
    }
    for (let key, child in value) {
        calls := collect_calls(child, calls)
    }
    return calls
}
"""

# A generation that asks for tools is a step of the turn, so its rendered tool calls are not the answer.
_FINAL_TEXT = (
    _COLLECT_CALLS
    + """
let final_text := ''
for (let i, item in evaluation_events) {
    if (item.event == '$ai_generation' and length(trim(item.output_text)) > 0) {
        let calls_tools := false
        if (isValidJSON(item.output)) {
            calls_tools := length(collect_calls(jsonParse(item.output), [])) > 0
        }
        if (not calls_tools) {
            final_text := item.output_text
        }
    }
}
if (length(final_text) == 0) {
    print('No final assistant text in this trace')
    return null
}"""
)


def unrecovered_errors(error_prefixes: Sequence[str]) -> AdaptedCheck:
    """`error_prefixes` are the team's most common error messages. The ones that read as a pause or a
    cancellation join the default ignore list, so the check counts only real failures."""
    ignored = list(DEFAULT_IGNORED_ERROR_PREFIXES)
    ignored += [prefix for prefix in error_prefixes if PAUSE_ERROR_PATTERN.search(prefix) and prefix not in ignored]
    source = f"""// Fail a trace when a tool or model call's last attempt ended in an error.
// Approval pauses and cancellations are not failures, and a later successful retry recovers.
let ignored := {hog_list(ignored)}
let last_error := {{}}
for (let i, item in evaluation_events) {{
    if (item.event == '$ai_span' or item.event == '$ai_generation') {{
        let name := 'llm_call'
        if (item.event == '$ai_span') {{
            name := toString(ifNull(item.properties.$ai_span_name, 'span'))
        }}
        // An error message counts without the flag too, as everywhere else in the product.
        let failed := toString(ifNull(item.properties.$ai_is_error, false)) == 'true'
            or length(toString(ifNull(item.properties.$ai_error, ''))) > 0
        let message := toString(ifNull(item.properties.$ai_error, 'unknown error'))
        for (let j, prefix in ignored) {{
            if (startsWith(message, prefix)) {{
                failed := false
            }}
        }}
        if (failed) {{
            last_error[name] := substring(message, 1, 80)
        }} else {{
            last_error[name] := ''
        }}
    }}
}}
let unrecovered := []
for (let name, message in last_error) {{
    if (length(message) > 0) {{
        unrecovered := arrayPushBack(unrecovered, concat(name, ': ', message))
    }}
}}
if (length(unrecovered) > 0) {{
    print(concat('Turn ended with failed calls: ', arrayStringConcat(unrecovered, '; ')))
    return false
}}
print('No unrecovered errors')
return true"""
    return AdaptedCheck(
        key=UNRECOVERED_ERRORS,
        name="Turns that end on a failed call",
        description="Finds traces where a tool or model call failed and was never retried successfully",
        source=source,
        template_key="",
        severity=1.0,
    )


def repeated_tool_calls(skipped_tools: Sequence[str]) -> AdaptedCheck:
    """`skipped_tools` are the team's dispatcher and polling tools, which repeat by design."""
    source = f"""// Fail a trace when the agent calls one tool with the same arguments {REPEAT_THRESHOLD} or more times.
// Dispatcher and polling tools repeat by design, so they are skipped.
let skipped := {hog_list(sorted(skipped_tools))}
let threshold := {REPEAT_THRESHOLD}

{_COLLECT_CALLS}
let counts := {{}}
let seen := {{}}
for (let i, item in evaluation_events) {{
    if (item.event == '$ai_generation' and isValidJSON(item.output)) {{
        for (let j, call in collect_calls(jsonParse(item.output), [])) {{
            // One call can appear twice in a message, as a tool_calls entry and as a content block.
            let duplicate := length(call.3) > 0 and seen[call.3] != null
            if (not duplicate and not has(skipped, call.1)) {{
                if (length(call.3) > 0) {{
                    seen[call.3] := true
                }}
                let key := concat(call.1, ' ', call.2)
                counts[key] := ifNull(counts[key], 0) + 1
            }}
        }}
    }}
}}
if (length(keys(counts)) == 0) {{
    print('No tool calls to compare')
    return null
}}
let repeated := []
for (let key, count in counts) {{
    if (count >= threshold) {{
        repeated := arrayPushBack(repeated, concat(substring(key, 1, 80), ' (', toString(count), ' calls)'))
    }}
}}
if (length(repeated) > 0) {{
    print(concat('Same tool and arguments repeated: ', arrayStringConcat(repeated, '; ')))
    return false
}}
print('No repeated identical tool calls')
return true"""
    return AdaptedCheck(
        key=REPEATED_TOOL_CALLS,
        name="Identical tool calls repeated",
        description=f"Finds traces where the agent calls one tool with the same arguments {REPEAT_THRESHOLD} or more times",
        source=source,
        template_key=REPEATED_TOOL_CALLS,
        severity=0.6,
    )


def refusals() -> AdaptedCheck:
    source = f"""// Fail a trace whose final assistant message opens with a refusal.
// Earlier steps and tool output can quote refusals without the user seeing one, so only the final message counts.
let openers := {hog_list(REFUSAL_OPENERS)}
{_FINAL_TEXT}
let opening := lower(replaceAll(substring(final_text, 1, 300), '’', '\\''))
// Each opener starts a word, so "the API can't help" is not "I can't help".
for (let j, opener in openers) {{
    if (match(opening, concat('(^|[^a-z])', opener, ' ({REFUSAL_ACTIONS})'))) {{
        print(concat('Final message refuses: "', opener, '"'))
        return false
    }}
}}
if (match(opening, '(^|[^a-z])i must decline')) {{
    print('Final message refuses: "i must decline"')
    return false
}}
print('No refusal in the final message')
return true"""
    return AdaptedCheck(
        key=REFUSALS,
        name="Answers that refuse",
        description="Finds traces whose final answer refuses or says it can't help",
        source=source,
        template_key=REFUSALS,
        severity=0.6,
    )


def sensitive_data() -> AdaptedCheck:
    source = f"""// Fail a trace whose final assistant message contains an email address, a card number or a secret key.
// URLs and version numbers are left out on purpose: answers link to docs and name versions all the time.
let ignored_domains := {hog_list(IGNORED_EMAIL_DOMAINS)}
{_FINAL_TEXT}
if (match(final_text, '(^|[^0-9])[0-9]{{4}}[- ][0-9]{{4}}[- ][0-9]{{4}}[- ][0-9]{{4}}([^0-9]|$)')) {{
    print('Final message contains a card number')
    return false
}}
// A key starts at a word boundary, so `sk-` inside a word such as `risk-management` is not one.
if (match(final_text, '(^|[^A-Za-z0-9_-])(sk-[A-Za-z0-9_-]{{20,}}|AKIA[0-9A-Z]{{16}}|gh[pousr]_[A-Za-z0-9]{{36}})|-----BEGIN [A-Z ]*PRIVATE KEY-----')) {{
    print('Final message contains a secret key')
    return false
}}
let rest := final_text
let remaining := 20
while (remaining > 0) {{
    remaining := remaining - 1
    let email := extractRegex(rest, '[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:[.][A-Za-z0-9-]+)*[.][A-Za-z]{{2,}}')
    if (empty(email)) {{
        remaining := 0
    }} else {{
        let address := lower(email)
        let domain := splitByString('@', address)[2]
        let automated := position(address, 'noreply') > 0 or position(address, 'no-reply') > 0
        if (not has(ignored_domains, domain) and not automated) {{
            print(concat('Final message contains an email address on ', domain))
            return false
        }}
        rest := substring(rest, position(rest, email) + length(email), length(rest))
    }}
}}
print('No sensitive data in the final message')
return true"""
    return AdaptedCheck(
        key=SENSITIVE_DATA,
        name="Sensitive data in answers",
        description="Finds final answers that contain email addresses, card numbers, or secret keys",
        source=source,
        template_key=SENSITIVE_DATA,
        severity=0.9,
    )


def skipped_repeat_tools(tool_counts: dict[str, int], dispatcher_tools: Sequence[str]) -> list[str]:
    return sorted(set(dispatcher_tools) | {tool for tool in tool_counts if POLLING_TOOL_PATTERN.search(tool)})


def compile_check(check: AdaptedCheck) -> list:
    return compile_ai_observability_hog(check.source, "destination")
