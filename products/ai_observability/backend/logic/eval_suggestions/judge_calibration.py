"""Stage 7, after the review: a drafted judge is shown only when the model it will run on agrees with the review.

The review labels every call it read for each card. The card's judge prompt then grades the review's fails and
passes on the team's runtime judge model, one call per request, with the runtime judge's own prompts. A small
model can miss most of the failures a strong model finds, so a card is kept only when its judge catches most of
the review's fails without flagging many of its passes.

A card can also carry a Hog code check from the review. That code runs on the review's calls for free, and when it
meets the same bar as a judge, the card becomes a code check and its judge is not calibrated.
"""

import json
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import Any, Literal

import httpx
import openai
import anthropic
import structlog
from anthropic.types import ToolParam, ToolUseBlock
from google import genai
from google.genai import (
    errors as genai_errors,
    types as genai_types,
)
from pydantic import ValidationError
from rest_framework import serializers

from posthog.hogql import ast
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.parser import parse_program
from posthog.hogql.visitor import TraversingVisitor

from posthog.dataclasses import frozen
from posthog.llm.gateway_client import (
    GatewayNotConfiguredError,
    build_gemini_client,
    build_openai_client,
    team_distinct_id,
)

from products.ai_observability.backend.hog import compile_ai_observability_hog
from products.ai_observability.backend.llm import DEFAULT_MODEL_BY_PROVIDER
from products.ai_observability.backend.llm.providers.gemini import GeminiConfig
from products.ai_observability.backend.logic.evaluations.hog_runtime import (
    HOG_EVAL_TIMEOUT,
    build_hog_event_global,
    execute_hog_eval_bytecode,
)
from products.ai_observability.backend.logic.evaluations.judge_prompts import (
    BooleanWithNAEvalResult,
    build_system_prompt,
    build_user_prompt,
)
from products.ai_observability.backend.logic.message_utils import format_tool_definitions

from common.hogvm.python.stl import STL
from common.hogvm.python.stl.bytecode import BYTECODE_STL

from . import call_review
from .call_review import Rendering, ReviewCard, Verdict
from .call_review_queries import ReviewCallRow
from .config import AI_PRODUCT
from .prices import MODEL_PRICES

logger = structlog.get_logger(__name__)

CALIBRATION_CALLS = 40
CONCURRENCY = 8
TIMEOUT_SECONDS = 30.0
# Room for a reasoning model's hidden tokens before a one-sentence verdict.
MAX_OUTPUT_TOKENS = 2048
# A judge that misses more than 2 in 5 of the review's fails would hide the failure its card is about.
MIN_CAUGHT_SHARE = 0.6
# One false alarm per two review fails at most, counted over every call the review labelled, so the real failures
# stay the bulk of what the judge flags.
FAILS_PER_FALSE_ALARM = 2
# A judge is trusted on calls it should pass only after it returned a verdict on this many, so a judge that fails
# everything, or whose requests on passes all failed, cannot look clean.
MIN_JUDGED_PASSES = 5
Provider = Literal["openai", "anthropic", "gemini"]
JudgeClient = anthropic.Anthropic | openai.OpenAI | genai.Client
# A judge on a model without a route here is not calibrated, so the review does not run for it.
GATEWAY_PROVIDERS: dict[str, Provider] = {
    DEFAULT_MODEL_BY_PROVIDER["openai"]: "openai",
    DEFAULT_MODEL_BY_PROVIDER["anthropic"]: "anthropic",
    DEFAULT_MODEL_BY_PROVIDER["gemini"]: "gemini",
}
# google-genai raises httpx transport failures, such as a connection reset or a read timeout, without wrapping them.
_CALL_ERRORS = (anthropic.APIError, openai.APIError, genai_errors.APIError, httpx.TransportError)

# BooleanWithNAEvalResult's fields, in the subset every provider's structured output accepts.
_VERDICT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "reasoning": {"type": "string"},
        "outcome": {"type": "string", "enum": ["pass", "fail", "not_applicable"]},
    },
    "required": ["reasoning", "outcome"],
    "additionalProperties": False,
}
_VERDICT_TOOL: ToolParam = {
    "name": "record_verdict",
    "description": "Record the verdict on the generation.",
    "input_schema": _VERDICT_SCHEMA,
}
_OUTCOME_VERDICTS: dict[str, Verdict] = {"pass": "pass", "fail": "fail", "not_applicable": "na"}


@frozen
class JudgeRequest:
    model: str
    system: str
    prompt: str


@frozen
class JudgeCall:
    # None when every attempt failed or the reply held no verdict.
    verdict: Verdict | None
    cost_usd: float


@frozen
class Calibration:
    review_fails: int
    caught: int
    # A call the review found the question does not apply to counts as a pass: the evaluation runs on it too, and a
    # fail there is a false alarm.
    review_passes: int
    # Review passes the judge returned a verdict on. Only these can show a false alarm.
    judged_passes: int
    false_alarms: int
    # Calls without a verdict: the request failed, the reply held none, or the deadline left no time to start it.
    unjudged: int
    # Review fails and passes the judge answered na on. A runtime fail rate leaves na answers out.
    na_on_fails: int
    na_on_passes: int


@frozen
class _Projection:
    """The judge's verdicts on the calibration calls, scaled to every call the review labelled."""

    review_fails: int
    caught: float
    false_alarms: float
    na: float


def provider(model: str | None) -> Provider | None:
    return GATEWAY_PROVIDERS.get(model) if model else None


def build_client(team_id: int, run_id: str, model: str, trigger: str) -> JudgeClient:
    """A Go gateway client for the model's provider, in privacy mode with the review's product tag, team and
    trigger."""
    kind = provider(model)
    if kind == "anthropic":
        return call_review.build_client(team_id, run_id, trigger)
    if kind == "gemini":
        gemini = build_gemini_client(
            ai_product=AI_PRODUCT,
            trace_id=run_id,
            properties={"team_id": str(team_id), "trigger": trigger},
            distinct_id=team_distinct_id(team_id),
            privacy_mode=True,
            timeout_ms=int(TIMEOUT_SECONDS * 1000),
        )
        if gemini is None:
            raise GatewayNotConfiguredError("AI_GATEWAY_URL and AI_GATEWAY_API_KEY must be configured")
        return gemini
    if kind is None:
        raise ValueError(f"No gateway route to calibrate on {model}")
    client = build_openai_client(
        # Only the Python gateway reads this route, and privacy mode raises instead of falling back to it.
        "django",
        ai_product=AI_PRODUCT,
        trace_id=run_id,
        properties={"team_id": str(team_id), "trigger": trigger},
        distinct_id=team_distinct_id(team_id),
        privacy_mode=True,
    )
    return client.with_options(max_retries=0)


def calibration_calls(card: ReviewCard) -> list[int]:
    """The review's fails and passes, CALIBRATION_CALLS at most, half for each when both have that many: a judge
    tested on fails alone would pass by failing everything. The pass slots go to real passes and to calls the
    question does not apply to in their own proportion, so the judge's verdicts on them stand for both kinds."""
    labels = sorted(card.labels.items())
    fails = [number for number, verdict in labels if verdict == "fail"]
    passes = [number for number, verdict in labels if verdict == "pass"]
    skipped = [number for number, verdict in labels if verdict == "na"]
    fail_slots = max(CALIBRATION_CALLS // 2, CALIBRATION_CALLS - len(passes) - len(skipped))
    picked_fails = fails[:fail_slots]
    slots = CALIBRATION_CALLS - len(picked_fails)
    share = round(slots * len(passes) / (len(passes) + len(skipped))) if passes or skipped else 0
    pass_slots = min(len(passes), max(share, slots - len(skipped)))
    return picked_fails + passes[:pass_slots] + skipped[: slots - pass_slots]


def judge_request(card: ReviewCard, rendering: Rendering, number: int, model: str) -> JudgeRequest:
    """The request the accepted evaluation will send for this call: the draft is a boolean judge that allows N/A,
    and the call is rendered by the runtime judge's own prompt builder."""
    row = rendering.calls[number].row
    # A catalog cut by the calls query's cap no longer parses, so it is left out rather than shown in pieces.
    catalog = _parsed(row.tools)
    tools = format_tool_definitions(catalog) if isinstance(catalog, list | dict) else ""
    prompt = build_user_prompt(_parsed(row.input), _parsed(row.output), tools)
    return JudgeRequest(
        model=model,
        system=build_system_prompt(card.judge_prompt, allows_na=True),
        # The calls query caps an output far below the judge's text limit, so the builder always returns a prompt.
        prompt=prompt or "",
    )


def _parsed(text: str) -> Any:
    """The JSON messages in `text`, or `text` itself. The runtime builder reads only messages and strings, and a
    bare number or null would make it raise."""
    try:
        value = json.loads(text)
    except (ValueError, RecursionError):
        return text
    return value if isinstance(value, list | dict | str) else text


def _verdict(answer: Any) -> Verdict | None:
    try:
        return _OUTCOME_VERDICTS[BooleanWithNAEvalResult.model_validate(answer).outcome]
    except ValidationError:
        return None


def _max_attempt_cost_usd(request: JudgeRequest) -> float:
    """A token covers at least one byte of the request, and output stops at MAX_OUTPUT_TOKENS."""
    price = MODEL_PRICES[request.model]
    request_bytes = len(json.dumps([request.system, request.prompt, _VERDICT_SCHEMA]).encode())
    return request_bytes * price.input_per_token + MAX_OUTPUT_TOKENS * price.output_per_token


def max_cost_usd(requests: Sequence[JudgeRequest]) -> float:
    """What the run reserves before the requests: the most every attempt of every request can bill together."""
    return call_review.ATTEMPTS * sum(_max_attempt_cost_usd(request) for request in requests)


def _json(text: str | None) -> Any:
    try:
        return json.loads(text or "")
    except ValueError:
        return None


def _attempt(client: JudgeClient, request: JudgeRequest) -> JudgeCall:
    price = MODEL_PRICES[request.model]
    if isinstance(client, anthropic.Anthropic):
        response = client.messages.create(
            model=request.model,
            max_tokens=MAX_OUTPUT_TOKENS,
            system=request.system,
            messages=[{"role": "user", "content": request.prompt}],
            tools=[_VERDICT_TOOL],
            tool_choice={"type": "tool", "name": _VERDICT_TOOL["name"]},
            timeout=TIMEOUT_SECONDS,
        )
        answer: Any = next((block.input for block in response.content if isinstance(block, ToolUseBlock)), None)
        usage = response.usage
        cost = usage.input_tokens * price.input_per_token + usage.output_tokens * price.output_per_token
    elif isinstance(client, genai.Client):
        reply = client.models.generate_content(
            model=request.model,
            contents=request.prompt,
            config=genai_types.GenerateContentConfig(
                system_instruction=request.system,
                temperature=GeminiConfig.TEMPERATURE,
                response_mime_type="application/json",
                response_json_schema=_VERDICT_SCHEMA,
                max_output_tokens=MAX_OUTPUT_TOKENS,
            ),
        )
        answer = _json(reply.text)
        metadata = reply.usage_metadata
        if metadata:
            # Gemini bills thinking tokens as output but counts them apart from the reply's tokens.
            output_tokens = (metadata.candidates_token_count or 0) + (metadata.thoughts_token_count or 0)
            cost = (metadata.prompt_token_count or 0) * price.input_per_token + output_tokens * price.output_per_token
        else:
            cost = _max_attempt_cost_usd(request)
    else:
        completion = client.chat.completions.create(
            model=request.model,
            messages=[{"role": "system", "content": request.system}, {"role": "user", "content": request.prompt}],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "verdict", "strict": True, "schema": _VERDICT_SCHEMA},
            },
            max_completion_tokens=MAX_OUTPUT_TOKENS,
            timeout=TIMEOUT_SECONDS,
        )
        answer = _json(completion.choices[0].message.content) if completion.choices else None
        tokens = completion.usage
        cost = (
            tokens.prompt_tokens * price.input_per_token + tokens.completion_tokens * price.output_per_token
            if tokens
            else _max_attempt_cost_usd(request)
        )
    return JudgeCall(verdict=_verdict(answer), cost_usd=cost)


def _rate_limited(error: Exception) -> bool:
    if isinstance(error, genai_errors.APIError):
        return error.code == 429
    return isinstance(error, anthropic.RateLimitError | openai.RateLimitError)


def _retryable(error: Exception) -> bool:
    if _rate_limited(error) or isinstance(
        error,
        anthropic.APIConnectionError
        | anthropic.InternalServerError
        | openai.APIConnectionError
        | openai.InternalServerError
        | genai_errors.ServerError
        | httpx.TransportError,
    ):
        return True
    if isinstance(error, genai_errors.APIError):
        # Google ends a call it cancelled with a 499 CANCELLED error, and a retry usually gets past it.
        return error.code == 499
    # The Anthropic SDK raises an overloaded 529 as its own class, which is not an InternalServerError.
    return isinstance(error, anthropic.APIStatusError | openai.APIStatusError) and error.status_code in (408, 529)


def judge(client: JudgeClient, request: JudgeRequest) -> JudgeCall:
    """One forced verdict. An attempt that fails may have billed, so it counts at its most, except a 429, which the
    provider refuses before any work. When every attempt fails, the call has no verdict."""
    unsettled = 0.0
    for attempt in range(call_review.ATTEMPTS):
        try:
            served = _attempt(client, request)
            return replace(served, cost_usd=served.cost_usd + unsettled)
        except _CALL_ERRORS as error:
            if not _rate_limited(error):
                unsettled += _max_attempt_cost_usd(request)
            if attempt == call_review.ATTEMPTS - 1 or not _retryable(error):
                logger.warning(
                    "eval_suggestions_calibration_call_failed", model=request.model, error=type(error).__name__
                )
                break
            time.sleep(call_review.RETRY_BACKOFF_SECONDS * (attempt + 1))
    return JudgeCall(verdict=None, cost_usd=unsettled)


def judge_all(client: JudgeClient, requests: Sequence[JudgeRequest], deadline: float | None) -> list[JudgeCall | None]:
    """Every request, CONCURRENCY at a time. A request starts only while its slowest run still ends before
    `deadline`, a time.monotonic() value. One that does not start is None and costs nothing."""

    def run(request: JudgeRequest) -> JudgeCall | None:
        if deadline is not None and time.monotonic() + call_review.max_seconds(TIMEOUT_SECONDS) > deadline:
            return None
        return judge(client, request)

    with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        return list(pool.map(run, requests))


def calibrate(card: ReviewCard, numbers: Sequence[int], verdicts: Sequence[Verdict | None]) -> Calibration:
    """The judge's verdicts on the calls `numbers` against the review's labels of them."""
    pairs = [(card.labels[number], verdict) for number, verdict in zip(numbers, verdicts, strict=True)]
    return Calibration(
        review_fails=sum(1 for label, _ in pairs if label == "fail"),
        caught=sum(1 for label, verdict in pairs if label == "fail" and verdict == "fail"),
        review_passes=sum(1 for label, _ in pairs if label != "fail"),
        judged_passes=sum(1 for label, verdict in pairs if label != "fail" and verdict is not None),
        false_alarms=sum(1 for label, verdict in pairs if label != "fail" and verdict == "fail"),
        unjudged=sum(1 for _, verdict in pairs if verdict is None),
        na_on_fails=sum(1 for label, verdict in pairs if label == "fail" and verdict == "na"),
        na_on_passes=sum(1 for label, verdict in pairs if label != "fail" and verdict == "na"),
    )


def _project(card: ReviewCard, calibration: Calibration) -> _Projection:
    """The judge's verdicts scaled to every call the review labelled. When the review passed more calls than the
    judge returned verdicts on, its verdicts on those stand for the rest too."""
    fails = sum(1 for verdict in card.labels.values() if verdict == "fail")
    fail_scale = fails / calibration.review_fails if calibration.review_fails else 0.0
    pass_scale = (len(card.labels) - fails) / calibration.judged_passes if calibration.judged_passes else 0.0
    return _Projection(
        review_fails=fails,
        caught=calibration.caught * fail_scale,
        false_alarms=calibration.false_alarms * pass_scale,
        na=calibration.na_on_fails * fail_scale + calibration.na_on_passes * pass_scale,
    )


def keeps(card: ReviewCard, calibration: Calibration) -> bool:
    fails = calibration.review_fails
    projected = _project(card, calibration)
    return (
        fails > 0
        and calibration.judged_passes >= MIN_JUDGED_PASSES
        and calibration.caught / fails >= MIN_CAUGHT_SHARE
        and projected.false_alarms <= max(1, projected.review_fails // FAILS_PER_FALSE_ALARM)
    )


def measured(card: ReviewCard, calibration: Calibration) -> ReviewCard:
    """The card with the judge's own counts over every call the review labelled: its fails, out of the calls it did
    not answer na on, as the evaluation's runtime rate counts them."""
    projected = _project(card, calibration)
    failed = round(projected.caught + projected.false_alarms)
    return replace(card, failed=failed, of=max(failed, round(len(card.labels) - projected.na)))


@frozen
class CodeCheck:
    source: str
    calibration: Calibration
    # The code's fails on the calls it was counted on, out of the calls it passed or failed.
    failed: int
    of: int
    # Calls whose data the code could not handle. Each one counts against the code in `calibration`.
    errors: int


# The functions the review prompt names. In one step the Python Hog VM can build a value far past its memory limit
# before checking it, through `*`, `%` on a string and some functions, so a generated check runs only when it stays
# inside this set.
_CODE_CHECK_FUNCTIONS = frozenset(
    {
        "length",
        "trim",
        "lower",
        "upper",
        "substring",
        "startsWith",
        "endsWith",
        "splitByString",
        "match",
        "isValidJSON",
        "jsonParse",
        "typeof",
        "keys",
        "has",
        "toString",
        "empty",
        "notEmpty",
        # A `for … in` loop compiles to a call to it.
        "values",
    }
)


_HOG_FUNCTIONS = frozenset(STL) | frozenset(BYTECODE_STL)
# The VM refuses these at dispatch too, which covers every way a call can reach a function.
_BLOCKED_FUNCTIONS = _HOG_FUNCTIONS - _CODE_CHECK_FUNCTIONS


class _OutsideCodeCheckSet(TraversingVisitor):
    found = False

    def visit_call(self, node: ast.Call) -> None:
        self.found = self.found or node.name not in _CODE_CHECK_FUNCTIONS
        super().visit_call(node)

    def visit_field(self, node: ast.Field) -> None:
        # A function read as a value could be called under an allowed name, as in `let match := replaceAll`.
        name = node.chain[0]
        self.found = self.found or (name in _HOG_FUNCTIONS and name not in _CODE_CHECK_FUNCTIONS)
        super().visit_field(node)

    # A variable under an allowed name could hold any function, such as one forged in data jsonParse returns, and a
    # call by that name would reach it. With none of these names bound, a call by name reaches the function itself.
    def binds(self, *names: str | int | None) -> None:
        self.found = self.found or any(name in _CODE_CHECK_FUNCTIONS for name in names)

    def visit_variable_declaration(self, node: ast.VariableDeclaration) -> None:
        self.binds(node.name)
        super().visit_variable_declaration(node)

    def visit_variable_assignment(self, node: ast.VariableAssignment) -> None:
        self.binds(*(node.left.chain[:1] if isinstance(node.left, ast.Field) else []))
        super().visit_variable_assignment(node)

    def visit_for_in_statement(self, node: ast.ForInStatement) -> None:
        self.binds(node.keyVar, node.valueVar)
        super().visit_for_in_statement(node)

    def visit_function(self, node: ast.Function) -> None:
        self.binds(node.name, *node.params)
        super().visit_function(node)

    def visit_try_catch_statement(self, node: ast.TryCatchStatement) -> None:
        self.binds(*(name for name, _, _ in node.catches))
        super().visit_try_catch_statement(node)

    def visit_lambda(self, node: ast.Lambda) -> None:
        self.binds(*node.args)
        super().visit_lambda(node)

    def visit_expr_call(self, node: ast.ExprCall) -> None:
        self.found = True
        super().visit_expr_call(node)

    def visit_arithmetic_operation(self, node: ast.ArithmeticOperation) -> None:
        self.found = self.found or node.op in (ast.ArithmeticOperationOp.Mult, ast.ArithmeticOperationOp.Mod)
        super().visit_arithmetic_operation(node)


class _TerminalHogError(Exception):
    """An error the evaluation runtime disables a Hog evaluation over, so a check that hits one is never published."""


def _code_verdict(bytecode: list[Any], row: ReviewCallRow) -> Verdict | None:
    """The code's verdict on one stored call, with the globals a generation evaluation gets, or None when this call's
    data defeated the code. Raises _TerminalHogError on any other error."""
    properties = {"$ai_input": _parsed(row.input), "$ai_output_choices": _parsed(row.output)}
    event = build_hog_event_global("$ai_generation", properties, event_uuid=row.event_uuid, timestamp=None)
    globals_dict = {
        "input": event["input"],
        "output": event["output"],
        "properties": properties,
        "event": {"uuid": row.event_uuid, "event": "$ai_generation", "distinct_id": ""},
        "evaluation_events": [event],
    }
    result = execute_hog_eval_bytecode(bytecode, globals_dict, allows_na=True, disallowed_functions=_BLOCKED_FUNCTIONS)
    if result["error"]:
        if result.get("user_input_error"):
            return None
        raise _TerminalHogError(result["error"])
    if result.get("applicable") is False:
        return "na"
    return "pass" if result["verdict"] else "fail"


def check_code(card: ReviewCard, rendering: Rendering, deadline: float | None) -> CodeCheck | None:
    """The card's code check run on every rendered call of its call types and compared with the review's labels, or
    None when it does not compile, steps outside the allowed functions and operators, hits an error the runtime
    would disable it over, or could run past `deadline`, a time.monotonic() value. An error on a call's data counts
    as the opposite of the label."""
    source = call_review.code_check_source(card.code_check)
    try:
        # compile_hog logs a syntax error as an error in our code. The parse catches the review's syntax errors first,
        # so they stay out of the error logs.
        program = parse_program(card.code_check)
        parse_program(source)
        bytecode = compile_ai_observability_hog(source, "destination")
    except (ExposedHogQLError, serializers.ValidationError):
        return None
    outside = _OutsideCodeCheckSet()
    outside.visit(program)
    if outside.found:
        return None
    keys = {call_type.key for call_type in card.call_types}
    verdicts: dict[int, Verdict | None] = {}
    for number, call in rendering.calls.items():
        if call.call_type not in keys:
            continue
        # Each call can run up to the Hog time limit, so one that starts later could eat into the judge fallback.
        if deadline is not None and time.monotonic() + HOG_EVAL_TIMEOUT.total_seconds() > deadline:
            return None
        try:
            verdicts[number] = _code_verdict(bytecode, call.row)
        except _TerminalHogError:
            return None
    numbers = sorted(card.labels)
    labelled: list[Verdict | None] = [
        verdicts.get(number) or ("pass" if card.labels[number] == "fail" else "fail") for number in numbers
    ]
    decided = [verdict for verdict in verdicts.values() if verdict in ("pass", "fail")]
    return CodeCheck(
        source=source,
        calibration=calibrate(card, numbers, labelled),
        failed=decided.count("fail"),
        of=len(decided),
        errors=sum(1 for verdict in verdicts.values() if verdict is None),
    )


def counted_on_day(
    card: ReviewCard, code: CodeCheck, rendering: Rendering, day: Sequence[ReviewCallRow], deadline: float | None
) -> CodeCheck | None:
    """`code`, which check_code kept, with the calls of `day` that the review did not read added to its counts, or
    None when one of them hits an error the runtime would disable the check over. Running out of time before
    `deadline` only stops the count."""
    keys = {call_type.key for call_type in card.call_types}
    read = {call.row.event_uuid for call in rendering.calls.values()}
    extra = [row for row in day if row.call_type in keys and row.event_uuid not in read]
    if not extra:
        return code
    bytecode = compile_ai_observability_hog(code.source, "destination")
    failed, of = code.failed, code.of
    for row in extra:
        if deadline is not None and time.monotonic() + HOG_EVAL_TIMEOUT.total_seconds() > deadline:
            break
        try:
            verdict = _code_verdict(bytecode, row)
        except _TerminalHogError:
            return None
        if verdict in ("pass", "fail"):
            of += 1
            failed += verdict == "fail"
    return replace(code, failed=failed, of=of)
