import os
import re
import sys
import copy
import random
import threading
import importlib.metadata
from collections.abc import Callable
from enum import StrEnum
from types import FrameType
from typing import Any, cast

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from cachetools import LRUCache
from hogql_parser import (
    parse_expr_json as _parse_expr_json_cpp,
    parse_full_template_string_json as _parse_full_template_string_json_cpp,
    parse_order_expr_json as _parse_order_expr_json_cpp,
    parse_program_json as _parse_program_json_cpp,
    parse_select_json as _parse_select_json_cpp,
)
from opentelemetry import trace
from prometheus_client import Counter, Gauge, Histogram
from structlog import getLogger

from posthog.hogql import ast
from posthog.hogql.constants import HogQLParserBackend
from posthog.hogql.errors import BaseHogQLError, ExposedHogQLError, SyntaxError
from posthog.hogql.json_ast import deserialize_ast
from posthog.hogql.placeholders import replace_placeholders
from posthog.hogql.timings import HogQLTimings
from posthog.hogql.visitor import clear_locations

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.schema_enums import ParserMode
from posthog.utils import safe_cache_add

logger = getLogger(__name__)

# Defensive import of the rust parser wheel. A packaging error (bad ABI,
# missing symbol, broken maturin build) shouldn't take the whole module
# down — `hogql_parser` (cpp) is still available as the production
# default, and the `*_shadow` parser modes can degrade to a no-op shadow
# leg until the wheel is repaired. Modes that explicitly select rust as
# the PRIMARY backend (`rust-json` / `RUST_ONLY` / `RUST_WITH_CPP_SHADOW`)
# will surface the RuntimeError below at parse time.
_RUST_PARSER_AVAILABLE = True
try:
    from hogql_parser_rs import (
        parse_expr_json as _parse_expr_json_rs,
        parse_expr_py as _parse_expr_py_rs,
        parse_full_template_string_json as _parse_full_template_string_json_rs,
        parse_full_template_string_py as _parse_full_template_string_py_rs,
        parse_order_expr_json as _parse_order_expr_json_rs,
        parse_order_expr_py as _parse_order_expr_py_rs,
        parse_program_json as _parse_program_json_rs,
        parse_program_py as _parse_program_py_rs,
        parse_select_json as _parse_select_json_rs,
        parse_select_py as _parse_select_py_rs,
    )
except ImportError as _import_err:
    _RUST_PARSER_AVAILABLE = False
    # Bind to a module-level name — `except as` bindings are deleted at
    # the end of the except block, so the closure below would otherwise
    # see an unbound `NameError` when called.
    _RUST_IMPORT_ERROR_REPR = repr(_import_err)
    logger.exception("hogql_parser_rs import failed; rust-json and rust-py backends disabled")
    capture_exception(
        _import_err,
        additional_properties={"hogql_parser_rs_import_error": _RUST_IMPORT_ERROR_REPR},
    )

    def _rust_parser_unavailable(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError(
            f"hogql_parser_rs is not importable (packaging error); original ImportError: {_RUST_IMPORT_ERROR_REPR}"
        )

    _parse_expr_json_rs = _rust_parser_unavailable
    _parse_full_template_string_json_rs = _rust_parser_unavailable
    _parse_order_expr_json_rs = _rust_parser_unavailable
    _parse_program_json_rs = _rust_parser_unavailable
    _parse_select_json_rs = _rust_parser_unavailable
    _parse_expr_py_rs = _rust_parser_unavailable
    _parse_full_template_string_py_rs = _rust_parser_unavailable
    _parse_order_expr_py_rs = _rust_parser_unavailable
    _parse_program_py_rs = _rust_parser_unavailable
    _parse_select_py_rs = _rust_parser_unavailable


class CacheOrigin(StrEnum):
    AUTO = "auto"
    BUILTIN = "builtin"
    USER = "user"


class ParseRule(StrEnum):
    EXPR = "expr"
    ORDER_EXPR = "order_expr"
    SELECT = "select"
    FULL_TEMPLATE_STRING = "full_template_string"
    PROGRAM = "program"


tracer = trace.get_tracer(__name__)


RULE_TO_PARSE_FUNCTION: dict[HogQLParserBackend, dict[ParseRule, Callable]] = {
    "cpp-json": {
        ParseRule.EXPR: lambda string, start: deserialize_ast(_parse_expr_json_cpp(string, is_internal=start is None)),
        ParseRule.ORDER_EXPR: lambda string: deserialize_ast(_parse_order_expr_json_cpp(string)),
        ParseRule.SELECT: lambda string: deserialize_ast(_parse_select_json_cpp(string)),
        ParseRule.FULL_TEMPLATE_STRING: lambda string: deserialize_ast(_parse_full_template_string_json_cpp(string)),
        ParseRule.PROGRAM: lambda string: deserialize_ast(_parse_program_json_cpp(string)),
    },
    "rust-json": {
        ParseRule.EXPR: lambda string, start: deserialize_ast(_parse_expr_json_rs(string, is_internal=start is None)),
        ParseRule.ORDER_EXPR: lambda string: deserialize_ast(_parse_order_expr_json_rs(string)),
        ParseRule.SELECT: lambda string: deserialize_ast(_parse_select_json_rs(string)),
        ParseRule.FULL_TEMPLATE_STRING: lambda string: deserialize_ast(_parse_full_template_string_json_rs(string)),
        ParseRule.PROGRAM: lambda string: deserialize_ast(_parse_program_json_rs(string)),
    },
    # `rust-py` skips JSON serialise/deserialise on both sides: the parser
    # builds a `serde_json::Value` (intermediate) and a Rust-side converter
    # constructs the Python ast dataclass instances directly via PyO3. The
    # `rust-json` path stays alongside for the future WASM build that can't
    # link to CPython, and for tests that need to compare on the JSON shape.
    "rust-py": {
        ParseRule.EXPR: lambda string, start: _parse_expr_py_rs(string, is_internal=start is None),
        ParseRule.ORDER_EXPR: _parse_order_expr_py_rs,
        ParseRule.SELECT: _parse_select_py_rs,
        ParseRule.FULL_TEMPLATE_STRING: _parse_full_template_string_py_rs,
        ParseRule.PROGRAM: _parse_program_py_rs,
    },
}


def _parser_version(distribution: str) -> str:
    """Installed version of a parser wheel, or "unknown" if it has no distribution metadata (editable/source build). Tagged on telemetry so old wheels can be filtered out."""
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


# Parser version per backend, resolved once at import. cpp/rust ship as wheels (`hogql-parser`, `hogql-parser-rs`).
_BACKEND_VERSION: dict[HogQLParserBackend, str] = {
    "cpp-json": _parser_version("hogql-parser"),
    "rust-json": _parser_version("hogql-parser-rs"),
    "rust-py": _parser_version("hogql-parser-rs"),
}

# Parse durations span ~10μs (rust-py) to a few ms (cpp typical) to seconds (pathological queries). Default Prometheus
# buckets bottom out at 5ms, so every sub-ms parse lands in the lowest bucket and histogram_quantile is useless at this
# scale; the 1-2-5 progression below gives usable resolution from 5μs through 10s.
_PARSE_DURATION_BUCKETS = (5e-6, 1e-5, 5e-5, 1e-4, 5e-4, 1e-3, 5e-3, 1e-2, 5e-2, 1e-1, 5e-1, 1, 5, 10)

RULE_TO_HISTOGRAM: dict[ParseRule, Histogram] = {
    rule: Histogram(
        f"parse_{rule}_seconds",
        f"Time to parse {rule} expression",
        labelnames=["backend", "version"],
        buckets=_PARSE_DURATION_BUCKETS,
    )
    for rule in (ParseRule.EXPR, ParseRule.ORDER_EXPR, ParseRule.SELECT, ParseRule.FULL_TEMPLATE_STRING)
}

DEFAULT_BACKEND: HogQLParserBackend = "cpp-json"


@frozen
class ResolvedParserBackends:
    primary: HogQLParserBackend
    shadow: HogQLParserBackend | None = None


# `parserMode` (a HogQLQueryModifier) selects the parser backend per query.
# Each mode maps to a primary/shadow backend pair: the primary parses
# the query and its result is always what's returned; a non-None shadow is
# run purely to detect divergence, on a small sample of accepted parses
# and on every rejected one.
_PARSER_MODE_BACKENDS: dict[ParserMode, ResolvedParserBackends] = {
    ParserMode.CPP_ONLY: ResolvedParserBackends(primary="cpp-json"),
    ParserMode.RUST_ONLY: ResolvedParserBackends(primary="rust-json"),
    ParserMode.CPP_WITH_RUST_SHADOW: ResolvedParserBackends(primary="cpp-json", shadow="rust-json"),
    ParserMode.CPP_WITH_RUST_PY_SHADOW: ResolvedParserBackends(primary="cpp-json", shadow="rust-py"),
    ParserMode.RUST_WITH_CPP_SHADOW: ResolvedParserBackends(primary="rust-json", shadow="cpp-json"),
    ParserMode.RUST_PY_ONLY: ResolvedParserBackends(primary="rust-py"),
    ParserMode.RUST_PY_WITH_CPP_SHADOW: ResolvedParserBackends(primary="rust-py", shadow="cpp-json"),
}

# Parser modes whose *primary* backend is the C++ parser. `parserMode` is a public
# `HogQLQueryModifier`, so a client can supply it — but the C++ backend's recursion guard is
# best-effort (a token pre-scan that can't bound recursive statement productions like nested
# `if`), so untrusted callers must not be able to force it as primary. cpp-as-*shadow* modes
# stay safe because the shadow legs bound what reaches cpp: the parity leg runs on 0.1% of
# parses the rust primary already accepted, and the rejection leg skips deeply nested input
# outright (`_is_shallow_enough_to_shadow`).
_CPP_PRIMARY_PARSER_MODES = frozenset(
    {ParserMode.CPP_ONLY, ParserMode.CPP_WITH_RUST_SHADOW, ParserMode.CPP_WITH_RUST_PY_SHADOW}
)


def sanitize_client_parser_mode(parser_mode: ParserMode | None) -> ParserMode | None:
    """Neutralize a client-supplied `parserMode` that would force the C++ backend as primary.

    Returns None (→ safe default resolution: rust-py primary, cpp sampled shadow) for
    cpp-primary modes, else the value unchanged. `parserMode` is an internal rollout knob
    never set by server-side code, so dropping these values costs nothing legitimate while
    closing the "authenticated caller selects the unguarded cpp parser" vector.
    """
    if parser_mode in _CPP_PRIMARY_PARSER_MODES:
        return None
    return parser_mode


# Fraction of `*_shadow` parses in PROD that also run the shadow backend. With rust-py promoted to the default primary,
# the shadow leg now runs the cpp parser on ~0.1% of requests purely as a divergence canary. Bump if a fresh regression
# surfaces and tighter coverage is needed.
_SHADOW_SAMPLE_RATE = 0.001


def _is_test_mode() -> bool:
    """Whether we're running under the test settings, without requiring Django to be configured.

    Reads Django's `settings.TEST` when settings are available; falls back to the `TEST` env var
    (then `False`) so the parser can run in environments that never boot Django (CLIs, workers,
    fuzzing scripts). Test mode only tightens parser behavior (100% shadow sampling, raise-on-
    divergence), so defaulting to non-test when settings are absent is safe for production paths.
    """
    try:
        return bool(settings.TEST)
    except ImproperlyConfigured:
        return os.environ.get("TEST", "").lower() in ("1", "true", "t")


def _shadow_sample_rate() -> float:
    """Shadow sampling fraction: 100% in tests (an explicitly requested shadow mode compares every parse, so
    regressions fail loud and deterministically), `_SHADOW_SAMPLE_RATE` in prod. Divergence behavior also differs
    by env (TEST raises, prod records) in `_run_shadow_comparison`."""
    return 1.0 if _is_test_mode() else _SHADOW_SAMPLE_RATE


def _resolve_parser_mode(parser_mode: ParserMode | None, backend: HogQLParserBackend | None) -> ResolvedParserBackends:
    """Resolve a `parserMode` modifier to primary/shadow backends.

    With neither `parser_mode` nor an explicit `backend=` set, the prod
    default is `RUST_PY_WITH_CPP_SHADOW`: rust-py is the primary (its result
    is always returned) and cpp runs as the shadow, sampled per
    `_shadow_sample_rate` (0.1% in prod), recording divergences without ever
    failing the request (`_run_shadow_comparison`).

    In TEST the default is `RUST_PY_ONLY` — no shadow. Prod's sampled shadow
    already provides cross-backend parity coverage over real traffic, and
    shadowing every test parse roughly doubled parser cost across the suite
    for no additional signal. Tests that exercise the shadow machinery itself
    opt in with an explicit `parser_mode`, which still shadow-compares 100%
    of parses and raises on divergence.

    If the rust wheel failed to import (`_RUST_PARSER_AVAILABLE` is False)
    the default falls back to cpp-only, so a broken wheel can't take the
    parse path down; the unavailability is reported once at import time.

    An explicit `backend=` override (test factories / parity scripts) is
    honoured untouched and bypasses the shadow — this includes
    `backend="cpp-json"`, which must NOT collapse into the default shadow
    pair because tests rely on it to opt into cpp-only parsing.
    Resolution happens here at the call site and is never written back
    onto the modifier, so the query hash is unaffected.

    `parser_mode` and `backend` are mutually exclusive: the first names a
    primary+shadow pair, the second forces a single backend with no shadow.
    Passing both is a caller error and raises, rather than silently letting
    one win.
    """
    if parser_mode is not None and backend is not None:
        raise ValueError(
            f"pass either parser_mode or backend, not both (got parser_mode={parser_mode}, backend={backend})"
        )
    if parser_mode is not None:
        return _PARSER_MODE_BACKENDS[parser_mode]
    if backend is not None:
        return ResolvedParserBackends(primary=backend)
    if _RUST_PARSER_AVAILABLE:
        if _is_test_mode():
            return _PARSER_MODE_BACKENDS[ParserMode.RUST_PY_ONLY]
        return _PARSER_MODE_BACKENDS[ParserMode.RUST_PY_WITH_CPP_SHADOW]
    return ResolvedParserBackends(primary=DEFAULT_BACKEND)


class HogQLParserShadowMismatch(Exception):
    """A `*_shadow` parser mode found the primary and shadow backends
    produced different ASTs. Reported to error tracking and never raised
    into a request — the primary backend's result is always returned."""


# Shadowed-run telemetry (sampled; see `_run_shadow_comparison`). This counter adds the run count + agreement rate;
# durations and their ratio come from the per-backend `parse_*_seconds` timer (the shadow runs on the already-done cpp
# parse). `*_version` labels let results be filtered by parser wheel. The raw query behind a divergence can't be a
# label, so it goes to error tracking via `capture_exception` (already a sink for query SQL on failures), not the logs.
_SHADOW_LABELNAMES = ["rule", "result", "primary_version", "shadow_version"]
_SHADOW_COMPARISONS = Counter(
    "hogql_parser_shadow_comparisons_total",
    "Shadowed parser runs by outcome. Sum across results is the number of "
    "shadowed runs; agreement rate is agree / that sum.",
    # result: agree | disagree | shadow_rejected | shadow_error
    labelnames=_SHADOW_LABELNAMES,
)


def _shadow_capture_properties(
    rule: ParseRule, statement: str, primary: HogQLParserBackend, shadow: HogQLParserBackend
) -> dict[str, Any]:
    """Capture properties both shadow legs attach. The query SQL can't be a metric label, so it rides error tracking —
    the channel that already carries query SQL on failures — rather than the logs."""
    return {
        "hogql_parser_rule": str(rule),
        "hogql_parser_primary": primary,
        "hogql_parser_shadow": shadow,
        "hogql_parser_primary_version": _BACKEND_VERSION.get(primary, "unknown"),
        "hogql_parser_shadow_version": _BACKEND_VERSION.get(shadow, "unknown"),
        "hogql_parser_statement": statement,
    }


def _run_shadow_comparison(
    rule: ParseRule,
    statement: str,
    primary_node: Any,
    start: int | None,
    *,
    backends: ResolvedParserBackends,
) -> None:
    """Cross-backend parity check, gated by `_shadow_sample_rate`. Emits telemetry only for shadowed runs, and always
    returns the primary result untouched.

    Increments `hogql_parser_shadow_comparisons_total` (run count + agreement rate, tagged by parser version). The
    shadow runs on the already-done cpp parse (never parsed twice); durations and their ratio come from the per-backend
    `parse_*_seconds` timer. The divergent query, which can't be a metric label, goes to error tracking via
    `capture_exception`, not the logs.

    Prod records divergences and shadow crashes without raising. TEST raises on a divergence or a shadow that rejects
    primary-accepted input; a packaging-class shadow failure (broken wheel, panic) is only counted. ASTs are compared
    INCLUDING per-node `start` / `end` positions — divergent spans are flagged "position-only" for triage.
    """
    if backends.shadow is None:
        return
    if random.random() >= _shadow_sample_rate():
        return
    test_mode = _is_test_mode()
    rule_label = str(rule)
    primary_version = _BACKEND_VERSION.get(backends.primary, "unknown")
    shadow_version = _BACKEND_VERSION.get(backends.shadow, "unknown")

    def _count(result: str) -> None:
        _SHADOW_COMPARISONS.labels(
            rule=rule_label, result=result, primary_version=primary_version, shadow_version=shadow_version
        ).inc()

    divergence_properties = _shadow_capture_properties(rule, statement, backends.primary, backends.shadow)
    try:
        shadow_node = _invoke_parser(backends.shadow, rule, statement, start)
    except BaseHogQLError as err:
        # Shadow rejects input the primary accepted: a divergence (raises in TEST).
        _count("shadow_rejected")
        capture_exception(err, additional_properties={**divergence_properties, "hogql_parser_shadow_throw": "true"})
        if test_mode:
            raise
        return
    except Exception as err:
        # Packaging-class failure (broken wheel / panic). Counted, never raised.
        _count("shadow_error")
        capture_exception(err, additional_properties={**divergence_properties, "hogql_parser_shadow_throw": "true"})
        return
    # Positions are part of the contract — the printer and planner consume cpp's per-node `start` / `end` spans, so a
    # span divergence is a real divergence. Compare full nodes; `clear_locations` is only used to classify a mismatch
    # as position-only vs structural for triage. Dataclass `==` reports a false mismatch for NaN-bearing ASTs
    # (`float("nan") != float("nan")`); repr is stable for NaN, so treat repr-equal as agreement too.
    if primary_node == shadow_node or repr(primary_node) == repr(shadow_node):
        _count("agree")
        return
    primary_cleared = clear_locations(primary_node)
    shadow_cleared = clear_locations(shadow_node)
    position_only = primary_cleared == shadow_cleared or repr(primary_cleared) == repr(shadow_cleared)
    kind = "position-only" if position_only else "structural"
    _count("disagree")
    # Include the offending statement so a failing test (or 1%-sample capture) is self-describing — the raised
    # exception is otherwise just "rule + backends". Truncate to keep the message bounded; the full statement is
    # also attached as a capture property via `divergence_properties`.
    excerpt = statement if len(statement) <= 2000 else statement[:2000] + "…(truncated)"
    mismatch = HogQLParserShadowMismatch(
        f"{rule} parser AST mismatch ({kind}): {backends.primary} vs {backends.shadow}\nstatement: {excerpt!r}"
    )
    if test_mode:
        raise mismatch
    capture_exception(
        mismatch,
        additional_properties={**divergence_properties, "hogql_parser_position_only_mismatch": position_only},
    )


class HogQLParserPrimaryOnlyRejection(Exception):
    """The primary backend refused a parse the shadow backend accepts — the signature of a
    primary-backend regression, as opposed to a syntax error in the query, which both
    backends refuse. Reported to error tracking and never raised into a request."""


# Rejection-leg telemetry. Separate from `_SHADOW_COMPARISONS` so that counter's agreement rate stays a ratio over
# successful parses.
_SHADOW_REJECTIONS = Counter(
    "hogql_parser_shadow_rejections_total",
    "Parses the primary backend refused, by what the shadow backend then did.",
    # result: both_rejected | shadow_accepted | shadow_error | skipped_deep_nesting
    labelnames=_SHADOW_LABELNAMES,
)

# Nesting bounds for the rejection leg. The cpp parser's cost grows superlinearly with nesting — around 0.16s at 24
# nested parentheses and 0.23s at 8 nested `if` statements, climbing into minutes beyond that. The parity leg only
# ever sees input the rust primary accepted, and is sampled at 0.1%; the rejection leg is unsampled and runs on input
# rust refused, so without a bound a caller could pin a worker with deeply nested invalid HogQL. These caps hold a
# shadow parse well under a second, and skipped parses are counted so the blind spot stays visible in the metric.
_REJECTION_SHADOW_MAX_NESTING = 24
_REJECTION_SHADOW_MAX_STATEMENT_KEYWORDS = 8
_STATEMENT_KEYWORD_PATTERN = re.compile(r"\b(?:if|while|for|fn)\b", re.IGNORECASE)

# Error-tracking capture from the rejection leg is throttled to at most one per signature per this window. The leg is
# unsampled and its designed operating condition — a sustained primary regression or a broken shadow wheel — makes
# every affected request reach a capture, so an un-throttled path rebuilds a stack trace per request and can crowd
# unrelated exceptions out of the shared telemetry queue. `_SHADOW_REJECTIONS` still counts every occurrence, so the
# metric keeps full volume while the captures stay a trickle.
_REJECTION_CAPTURE_THROTTLE_TTL = 300  # seconds


def _is_shallow_enough_to_shadow(rule: ParseRule, statement: str) -> bool:
    """Whether the shadow backend can parse `statement` within a bounded time. See `_REJECTION_SHADOW_MAX_NESTING`."""
    depth = 0
    for char in statement:
        if char in "([{":
            depth += 1
            if depth > _REJECTION_SHADOW_MAX_NESTING:
                return False
        elif char in ")]}":
            # Clamp so unbalanced closers can't buy depth back for a later run of openers.
            depth = max(0, depth - 1)
    # Nested Hog statements (`if (1) if (1) …`) recurse without adding bracket depth, so they need their own bound.
    # Only Hog programs take statements at the top level; elsewhere a statement must sit in a `{ … }` block. Checking
    # for the brace first keeps ordinary SQL out of the count, where `if` is a scalar function and runs into dozens.
    if rule is not ParseRule.PROGRAM and "{" not in statement:
        return True
    # Count with `finditer` and stop once past the cap. A keyword-heavy program has millions of matches, and `findall`
    # would allocate every one just to compare the length against a small bound — the cost this guard exists to avoid.
    keywords = 0
    for _ in _STATEMENT_KEYWORD_PATTERN.finditer(statement):
        keywords += 1
        if keywords > _REJECTION_SHADOW_MAX_STATEMENT_KEYWORDS:
            return False
    return True


def _run_rejection_shadow(
    rule: ParseRule,
    statement: str,
    primary_error: BaseHogQLError,
    start: int | None,
    *,
    backends: ResolvedParserBackends,
) -> None:
    """Ask the shadow backend about a parse the primary backend refused, and record the answer.

    Unsampled, unlike `_run_shadow_comparison` — a primary-only rejection is too rare to catch at 0.1%, and this leg
    only runs on a parse that already failed. The primary error always propagates; this leg records, it never changes
    what the caller sees. A query both backends refuse is a syntax error in the query, so it is counted and dropped
    rather than reported.
    """
    if backends.shadow is None:
        return
    rule_label = str(rule)
    primary_version = _BACKEND_VERSION.get(backends.primary, "unknown")
    shadow_version = _BACKEND_VERSION.get(backends.shadow, "unknown")

    def _count(result: str) -> None:
        _SHADOW_REJECTIONS.labels(
            rule=rule_label, result=result, primary_version=primary_version, shadow_version=shadow_version
        ).inc()

    def _capture_throttled(result: str, exc: BaseException) -> None:
        # One capture per (result, rule, backend pair) per TTL — see `_REJECTION_CAPTURE_THROTTLE_TTL`. The key omits
        # the query and the primary error, so varying the input can't force a fresh capture on a repeated signature.
        throttle_key = f"hogql_parser_rejection_capture:{result}:{rule_label}:{backends.primary}:{backends.shadow}"
        if safe_cache_add(throttle_key, True, _REJECTION_CAPTURE_THROTTLE_TTL):
            capture_exception(
                exc,
                additional_properties=_rejection_properties(
                    rule, statement, backends.primary, backends.shadow, primary_error
                ),
            )

    if not _is_shallow_enough_to_shadow(rule, statement):
        _count("skipped_deep_nesting")
        return
    try:
        _invoke_parser(backends.shadow, rule, statement, start)
    except ExposedHogQLError:
        # Both backends refuse the query for a user-facing reason: a fault in the query, not a regression.
        _count("both_rejected")
        return
    except Exception as err:
        # Broken shadow wheel or panic, surfaced as an InternalHogQLError (cpp raises ParsingError, rust wraps a
        # panic as NotImplementedError), plus any other unexpected failure. Counted and captured, never raised.
        _count("shadow_error")
        _capture_throttled("shadow_error", err)
        return
    _count("shadow_accepted")
    _capture_throttled(
        "shadow_accepted",
        HogQLParserPrimaryOnlyRejection(
            f"{rule} refused by {backends.primary} but parsed by {backends.shadow}: {primary_error}"
        ),
    )


def _rejection_properties(
    rule: ParseRule,
    statement: str,
    primary: HogQLParserBackend,
    shadow: HogQLParserBackend,
    primary_error: BaseHogQLError,
) -> dict[str, Any]:
    """Built lazily: `both_rejected` is the dominant outcome and reports nothing."""
    return {
        **_shadow_capture_properties(rule, statement, primary, shadow),
        "hogql_parser_primary_error": str(primary_error),
    }


# Two caches so a flood of unique user-generated queries can't displace the
# hot in-code-literal entries. Origin is auto-detected via the call-stack
# `co_consts` walk; callers can override via `cache_origin`.

_BUILTIN_CACHE_SIZE = 256
_USER_CACHE_SIZE = 512
_LITERAL_DETECTION_FRAME_DEPTH = 40
# Short identifier-shaped strings are auto-interned by CPython and can
# spuriously identity-match `co_consts` elsewhere, misrouting user input.
_LITERAL_DETECTION_MIN_LEN = 32

# Skip caching very short queries — they parse fast enough that caching
# adds no measurable speedup and they'd churn cache slots that longer,
# higher-value entries could use. Cap the upper end too, to bound memory
# from user-controlled inputs. Explicit `cache_origin=BUILTIN` bypasses
# only the upper bound (trusted opt-in for large queries — some in-code
# templates run past this).
_MIN_CACHEABLE_STATEMENT_LEN = 40
_MAX_CACHEABLE_STATEMENT_LEN = 4 * 1024

_PARSE_CACHE_EVENTS = Counter(
    "hogql_parse_cache_events_total",
    "HogQL parse-cache lookups",
    labelnames=["origin", "result", "rule"],
)
_PARSE_CACHE_SIZE = Gauge(
    "hogql_parse_cache_size",
    "Current entries in the HogQL parse cache (compare against the configured maxsize to spot saturation)",
    labelnames=["cache"],
    multiprocess_mode="livemax",
)
_PARSE_CACHE_MAXSIZE = Gauge(
    "hogql_parse_cache_maxsize",
    "Configured maxsize of the HogQL parse cache",
    labelnames=["cache"],
    multiprocess_mode="livemax",
)
# Bucket boundaries align with the cache size bounds (40 and 4096) so the
# fraction of statements below the min or above the max is directly
# readable from the histogram.
_PARSE_STATEMENT_LENGTH = Histogram(
    "hogql_parse_statement_length_chars",
    "Length of HogQL statements passed to the parser, in characters",
    labelnames=["rule"],
    buckets=(16, 32, 40, 64, 128, 256, 512, 1024, 2048, 4096, 8192, 32768, 131072, 524288),
)


def _looks_like_code_literal(s: str) -> bool:
    """True if ``s`` is a string literal somewhere in the active call stack.

    Python literals share identity with their frame's ``co_consts``;
    runtime-constructed strings don't. Module/class-level constants
    referenced via ``LOAD_GLOBAL`` are missed — callers pass
    ``cache_origin=CacheOrigin.BUILTIN`` explicitly for those.

    This is a best-effort heuristic. A wrong classification only affects
    which bucket a cache entry lands in; the returned AST is the same
    either way, so functional behavior is correct regardless. The cost
    of a miss is at worst a less-optimal cache layout.
    """
    if len(s) < _LITERAL_DETECTION_MIN_LEN:
        return False
    frame: FrameType | None = sys._getframe(1)
    for _ in range(_LITERAL_DETECTION_FRAME_DEPTH):
        if frame is None:
            return False
        for const in frame.f_code.co_consts:
            if const is s:
                return True
        frame = frame.f_back
    return False


# Sentinel distinguishes "key absent" from a cached ``None``.
_MISS: Any = object()

_builtin_parse_cache: LRUCache[Any, Any] = LRUCache(maxsize=_BUILTIN_CACHE_SIZE)
_user_parse_cache: LRUCache[Any, Any] = LRUCache(maxsize=_USER_CACHE_SIZE)
# `cachetools.LRUCache` is not thread-safe; the lock guards against
# threaded WSGI/Celery workers.
_PARSE_CACHE_LOCK = threading.Lock()

_PARSE_CACHE_MAXSIZE.labels(cache=CacheOrigin.BUILTIN).set(_BUILTIN_CACHE_SIZE)
_PARSE_CACHE_MAXSIZE.labels(cache=CacheOrigin.USER).set(_USER_CACHE_SIZE)


def _invoke_parser(backend: HogQLParserBackend, rule: ParseRule, statement: str, start: int | None) -> Any:
    fn = RULE_TO_PARSE_FUNCTION[backend][rule]
    # Histogram wraps only the parse so `parse_*_seconds` stays a parser-perf
    # signal regardless of cache hit rate. Only `expr` takes a `start` arg;
    # `PROGRAM` is the only rule without a histogram.
    histogram = RULE_TO_HISTOGRAM.get(rule)
    if histogram is None:
        return fn(statement)
    with histogram.labels(backend=backend, version=_BACKEND_VERSION.get(backend, "unknown")).time():
        return fn(statement, start) if rule == ParseRule.EXPR else fn(statement)


def _parse_cached(
    rule: ParseRule,
    statement: str,
    backend: HogQLParserBackend,
    cache_origin: CacheOrigin,
    *,
    start: int | None = None,
    classify_input: str | None = None,
) -> Any:
    """Look up a parsed AST, parsing on miss.

    ``AUTO`` consults both caches before classifying via frame walk, so the
    walk is on the cold path only. Explicit ``BUILTIN``/``USER`` only
    consult their own cache.

    ``classify_input`` lets callers key the cache on a derived string while
    classifying on the original (e.g. ``parse_string_template`` keys on
    ``"F'" + string`` but the frame literal it wants to match is ``string``).

    Returns a deepcopy on hit so the resolver/printer can mutate freely.
    The miss path returns the fresh parse directly and stores the deepcopy.
    """
    # Coerce so a stringly-typed call validates and a typo raises.
    cache_origin = CacheOrigin(cache_origin)

    _PARSE_STATEMENT_LENGTH.labels(rule=rule).observe(len(statement))

    if len(statement) < _MIN_CACHEABLE_STATEMENT_LEN or (
        cache_origin != CacheOrigin.BUILTIN and len(statement) > _MAX_CACHEABLE_STATEMENT_LEN
    ):
        _PARSE_CACHE_EVENTS.labels(origin=cache_origin, result="skip", rule=rule).inc()
        return _invoke_parser(backend, rule, statement, start)

    key = (statement, backend, rule, start)

    if cache_origin == CacheOrigin.AUTO:
        with _PARSE_CACHE_LOCK:
            cached = _builtin_parse_cache.get(key, _MISS)
            if cached is _MISS:
                cached = _user_parse_cache.get(key, _MISS)
                hit_origin = CacheOrigin.USER if cached is not _MISS else None
            else:
                hit_origin = CacheOrigin.BUILTIN
        if hit_origin is not None:
            _PARSE_CACHE_EVENTS.labels(origin=hit_origin, result="hit", rule=rule).inc()
            return copy.deepcopy(cached)
        cache_origin = (
            CacheOrigin.BUILTIN
            if _looks_like_code_literal(classify_input if classify_input is not None else statement)
            else CacheOrigin.USER
        )
    else:
        cache = _builtin_parse_cache if cache_origin == CacheOrigin.BUILTIN else _user_parse_cache
        with _PARSE_CACHE_LOCK:
            cached = cache.get(key, _MISS)
        if cached is not _MISS:
            _PARSE_CACHE_EVENTS.labels(origin=cache_origin, result="hit", rule=rule).inc()
            return copy.deepcopy(cached)

    # Parse outside the lock — it's the expensive part, and concurrent parses
    # of the same key race idempotently.
    cache = _builtin_parse_cache if cache_origin == CacheOrigin.BUILTIN else _user_parse_cache
    parsed = _invoke_parser(backend, rule, statement, start)
    cached_copy = copy.deepcopy(parsed)
    with _PARSE_CACHE_LOCK:
        cache[key] = cached_copy
        currsize = cache.currsize
    _PARSE_CACHE_EVENTS.labels(origin=cache_origin, result="miss", rule=rule).inc()
    _PARSE_CACHE_SIZE.labels(cache=cache_origin).set(currsize)
    return parsed


def _parse_with_shadow(
    rule: ParseRule,
    statement: str,
    resolved: ResolvedParserBackends,
    cache_origin: CacheOrigin,
    *,
    start: int | None = None,
    classify_input: str | None = None,
) -> Any:
    """Parse with the primary backend, then run whichever shadow leg the outcome calls for: the sampled parity check
    on a successful parse, the unsampled rejection check on a refused one."""
    try:
        node = _parse_cached(
            rule, statement, resolved.primary, cache_origin, start=start, classify_input=classify_input
        )
    except BaseHogQLError as err:
        _run_rejection_shadow(rule, statement, err, start, backends=resolved)
        raise
    _run_shadow_comparison(rule, statement, node, start, backends=resolved)
    return node


def clear_parse_caches() -> None:
    """Drop both parse caches. Used by tests."""
    with _PARSE_CACHE_LOCK:
        _builtin_parse_cache.clear()
        _user_parse_cache.clear()
    _PARSE_CACHE_SIZE.labels(cache=CacheOrigin.BUILTIN).set(0)
    _PARSE_CACHE_SIZE.labels(cache=CacheOrigin.USER).set(0)


def parse_string_template(
    string: str,
    placeholders: dict[str, ast.Expr] | None = None,
    timings: HogQLTimings | None = None,
    *,
    backend: HogQLParserBackend | None = None,
    parser_mode: ParserMode | None = None,
    cache_origin: CacheOrigin = CacheOrigin.AUTO,
) -> ast.Call:
    """Parse a full template string without start/end quotes"""
    if timings is None:
        timings = HogQLTimings()
    resolved = _resolve_parser_mode(parser_mode, backend)
    # The cache is keyed on `"F'" + string` (a runtime concat that never
    # matches a frame literal), so pass the raw `string` as the classify
    # target — that keeps the frame walk on the cold path here too.
    with timings.measure(f"parse_full_template_string_{resolved.primary}"):
        node = _parse_with_shadow(
            ParseRule.FULL_TEMPLATE_STRING,
            "F'" + string,
            resolved,
            cache_origin,
            classify_input=string,
        )
        if placeholders:
            with timings.measure("replace_placeholders"):
                node = replace_placeholders(node, placeholders)
    return cast("ast.Call", node)


def parse_expr(
    expr: str,
    placeholders: dict[str, ast.Expr] | None = None,
    start: int | None = 0,
    timings: HogQLTimings | None = None,
    *,
    backend: HogQLParserBackend | None = None,
    parser_mode: ParserMode | None = None,
    cache_origin: CacheOrigin = CacheOrigin.AUTO,
) -> ast.Expr:
    if expr == "":
        raise SyntaxError("Empty query")
    if timings is None:
        timings = HogQLTimings()
    resolved = _resolve_parser_mode(parser_mode, backend)
    with timings.measure(f"parse_expr_{resolved.primary}"):
        node = _parse_with_shadow(ParseRule.EXPR, expr, resolved, cache_origin, start=start)
        if placeholders:
            with timings.measure("replace_placeholders"):
                node = replace_placeholders(node, placeholders)
    return cast("ast.Expr", node)


def parse_order_expr(
    order_expr: str,
    placeholders: dict[str, ast.Expr] | None = None,
    timings: HogQLTimings | None = None,
    *,
    backend: HogQLParserBackend | None = None,
    parser_mode: ParserMode | None = None,
    cache_origin: CacheOrigin = CacheOrigin.AUTO,
) -> ast.OrderExpr:
    if timings is None:
        timings = HogQLTimings()
    resolved = _resolve_parser_mode(parser_mode, backend)
    with timings.measure(f"parse_order_expr_{resolved.primary}"):
        node = _parse_with_shadow(ParseRule.ORDER_EXPR, order_expr, resolved, cache_origin)
        if placeholders:
            with timings.measure("replace_placeholders"):
                node = replace_placeholders(node, placeholders)
    return cast("ast.OrderExpr", node)


def parse_select(
    statement: str,
    placeholders: dict[str, ast.Expr] | None = None,
    timings: HogQLTimings | None = None,
    *,
    backend: HogQLParserBackend | None = None,
    parser_mode: ParserMode | None = None,
    cache_origin: CacheOrigin = CacheOrigin.AUTO,
) -> ast.SelectQuery | ast.SelectSetQuery:
    if timings is None:
        timings = HogQLTimings()
    resolved = _resolve_parser_mode(parser_mode, backend)
    with timings.measure(f"parse_select_{resolved.primary}"):
        with tracer.start_as_current_span("parse_statement_to_node"):
            node = _parse_with_shadow(ParseRule.SELECT, statement, resolved, cache_origin)
        if placeholders:
            with timings.measure("replace_placeholders"), tracer.start_as_current_span("replace_placeholders"):
                node = replace_placeholders(node, placeholders)
    return cast("ast.SelectQuery | ast.SelectSetQuery", node)


def parse_program(
    source: str,
    timings: HogQLTimings | None = None,
    *,
    backend: HogQLParserBackend | None = None,
    parser_mode: ParserMode | None = None,
    cache_origin: CacheOrigin = CacheOrigin.AUTO,
) -> ast.Program:
    if timings is None:
        timings = HogQLTimings()
    resolved = _resolve_parser_mode(parser_mode, backend)
    with timings.measure(f"parse_program_{resolved.primary}"):
        node = _parse_with_shadow(ParseRule.PROGRAM, source, resolved, cache_origin)
    return cast("ast.Program", node)
