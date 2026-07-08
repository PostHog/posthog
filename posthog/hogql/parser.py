import sys
import copy
import random
import hashlib
import threading
import importlib.metadata
from collections.abc import Callable
from enum import StrEnum
from types import FrameType
from typing import Any, cast

from django.conf import settings

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
from posthog.hogql.errors import BaseHogQLError, SyntaxError
from posthog.hogql.json_ast import deserialize_ast
from posthog.hogql.placeholders import replace_placeholders
from posthog.hogql.timings import HogQLTimings
from posthog.hogql.visitor import clear_locations

from posthog.exceptions_capture import capture_exception
from posthog.schema_enums import ParserMode

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


# `parserMode` (a HogQLQueryModifier) selects the parser backend per query.
# Each mode maps to a `(primary, shadow)` backend pair: the primary parses
# the query and its result is always what's returned; a non-None shadow is
# run on a small sample of parses purely to detect divergence.
_PARSER_MODE_BACKENDS: dict[ParserMode, tuple[HogQLParserBackend, HogQLParserBackend | None]] = {
    ParserMode.CPP_ONLY: ("cpp-json", None),
    ParserMode.RUST_ONLY: ("rust-json", None),
    ParserMode.CPP_WITH_RUST_SHADOW: ("cpp-json", "rust-json"),
    ParserMode.CPP_WITH_RUST_PY_SHADOW: ("cpp-json", "rust-py"),
    ParserMode.RUST_WITH_CPP_SHADOW: ("rust-json", "cpp-json"),
    ParserMode.RUST_PY_ONLY: ("rust-py", None),
    ParserMode.RUST_PY_WITH_CPP_SHADOW: ("rust-py", "cpp-json"),
}

# Fraction of `*_shadow` parses in PROD that also run the shadow backend. With rust-py promoted to the default primary,
# the shadow leg now runs the cpp parser on ~0.1% of requests purely as a divergence canary. Bump if a fresh regression
# surfaces and tighter coverage is needed. Tests always sample 100%.
_SHADOW_SAMPLE_RATE = 0.001


def _shadow_sample_rate() -> float:
    """Shadow sampling fraction: 100% in tests (every parse compared, regressions fail loud), `_SHADOW_SAMPLE_RATE` in
    prod. Divergence behavior also differs by env (TEST raises, prod records) in `_run_shadow_comparison`."""
    return 1.0 if settings.TEST else _SHADOW_SAMPLE_RATE


def _resolve_parser_mode(
    parser_mode: ParserMode | None, backend: HogQLParserBackend | None
) -> tuple[HogQLParserBackend, HogQLParserBackend | None]:
    """Resolve a `parserMode` modifier to `(primary, shadow)` backends.

    With neither `parser_mode` nor an explicit `backend=` set, the default is
    `RUST_PY_WITH_CPP_SHADOW`: rust-py is the primary (its result is always
    returned) and cpp runs as the shadow, sampled per `_shadow_sample_rate`
    (100% in test, 0.1% in prod). The divergence behavior differs by
    environment downstream (`_run_shadow_comparison`): TEST raises on any
    mismatch, prod only reports it (never failing the request).

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
        return backend, None
    if _RUST_PARSER_AVAILABLE:
        return _PARSER_MODE_BACKENDS[ParserMode.RUST_PY_WITH_CPP_SHADOW]
    return DEFAULT_BACKEND, None


class HogQLParserShadowMismatch(Exception):
    """A `*_shadow` parser mode found the primary and shadow backends
    produced different ASTs. Reported to error tracking and never raised
    into a request — the primary backend's result is always returned."""


# Shadowed-run telemetry (sampled; see `_run_shadow_comparison`). This counter adds the run count + agreement rate;
# durations and their ratio come from the per-backend `parse_*_seconds` timer (the shadow runs on the already-done cpp
# parse). `*_version` labels let results be filtered by parser wheel. The raw query behind a divergence can't be a
# label, so it goes to error tracking via `capture_exception` (already a sink for query SQL on failures), not the logs.
_SHADOW_COMPARISONS = Counter(
    "hogql_parser_shadow_comparisons_total",
    "Shadowed parser runs by outcome. Sum across results is the number of "
    "shadowed runs; agreement rate is agree / that sum.",
    # result: agree | disagree | shadow_rejected | shadow_error
    labelnames=["rule", "result", "primary_version", "shadow_version"],
)


# Tests shadow-compare every parse (sample rate 1.0), and the same in-code
# statements recur across tests thousands of times per process. Both backends
# are deterministic functions of (rule, statement, start), so a comparison
# that already agreed can never disagree on repeat — remember agreed keys (by
# statement digest) and skip the redundant shadow parse. A divergence still
# raises the first time the statement is seen. TEST-only: prod samples 0.1%
# and its telemetry should keep counting every sampled run.
_shadow_agreed_in_tests: set[tuple[str, str, str, int | None, bytes]] = set()
_SHADOW_AGREED_MAX_ENTRIES = 100_000


def clear_shadow_agreed_for_tests() -> None:
    """Reset the TEST-mode dedup set.

    Tests that patch _invoke_parser (or either backend) to force a divergence on a
    previously-agreed statement must call this first — otherwise the cached agreement
    short-circuits the shadow run and the forced divergence is never observed.
    """
    _shadow_agreed_in_tests.clear()


def _run_shadow_comparison(
    rule: ParseRule,
    statement: str,
    primary_backend: HogQLParserBackend,
    shadow_backend: HogQLParserBackend,
    primary_node: Any,
    start: int | None,
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
    if random.random() >= _shadow_sample_rate():
        return
    test_mode = settings.TEST
    dedup_key = None
    if test_mode:
        dedup_key = (
            str(rule),
            str(primary_backend),
            str(shadow_backend),
            start,
            hashlib.sha256(statement.encode()).digest(),
        )
        if dedup_key in _shadow_agreed_in_tests:
            return
    rule_label = str(rule)
    primary_version = _BACKEND_VERSION.get(primary_backend, "unknown")
    shadow_version = _BACKEND_VERSION.get(shadow_backend, "unknown")

    def _count(result: str) -> None:
        _SHADOW_COMPARISONS.labels(
            rule=rule_label, result=result, primary_version=primary_version, shadow_version=shadow_version
        ).inc()

    # Divergent query SQL rides error tracking (not the logs), the channel that already carries query SQL on failures.
    divergence_properties = {
        "hogql_parser_rule": rule_label,
        "hogql_parser_primary": primary_backend,
        "hogql_parser_shadow": shadow_backend,
        "hogql_parser_primary_version": primary_version,
        "hogql_parser_shadow_version": shadow_version,
        "hogql_parser_statement": statement,
    }
    try:
        shadow_node = _invoke_parser(shadow_backend, rule, statement, start)
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
        if dedup_key is not None and len(_shadow_agreed_in_tests) < _SHADOW_AGREED_MAX_ENTRIES:
            _shadow_agreed_in_tests.add(dedup_key)
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
        f"{rule} parser AST mismatch ({kind}): {primary_backend} vs {shadow_backend}\nstatement: {excerpt!r}"
    )
    if test_mode:
        raise mismatch
    capture_exception(
        mismatch,
        additional_properties={**divergence_properties, "hogql_parser_position_only_mismatch": position_only},
    )


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
    primary, shadow = _resolve_parser_mode(parser_mode, backend)
    # The cache is keyed on `"F'" + string` (a runtime concat that never
    # matches a frame literal), so pass the raw `string` as the classify
    # target — that keeps the frame walk on the cold path here too.
    with timings.measure(f"parse_full_template_string_{primary}"):
        node = _parse_cached(
            ParseRule.FULL_TEMPLATE_STRING,
            "F'" + string,
            primary,
            cache_origin,
            classify_input=string,
        )
        if shadow is not None:
            _run_shadow_comparison(ParseRule.FULL_TEMPLATE_STRING, "F'" + string, primary, shadow, node, None)
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
    primary, shadow = _resolve_parser_mode(parser_mode, backend)
    with timings.measure(f"parse_expr_{primary}"):
        node = _parse_cached(ParseRule.EXPR, expr, primary, cache_origin, start=start)
        if shadow is not None:
            _run_shadow_comparison(ParseRule.EXPR, expr, primary, shadow, node, start)
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
    primary, shadow = _resolve_parser_mode(parser_mode, backend)
    with timings.measure(f"parse_order_expr_{primary}"):
        node = _parse_cached(ParseRule.ORDER_EXPR, order_expr, primary, cache_origin)
        if shadow is not None:
            _run_shadow_comparison(ParseRule.ORDER_EXPR, order_expr, primary, shadow, node, None)
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
    primary, shadow = _resolve_parser_mode(parser_mode, backend)
    with timings.measure(f"parse_select_{primary}"):
        with tracer.start_as_current_span("parse_statement_to_node"):
            node = _parse_cached(ParseRule.SELECT, statement, primary, cache_origin)
        if shadow is not None:
            _run_shadow_comparison(ParseRule.SELECT, statement, primary, shadow, node, None)
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
    primary, shadow = _resolve_parser_mode(parser_mode, backend)
    with timings.measure(f"parse_program_{primary}"):
        node = _parse_cached(ParseRule.PROGRAM, source, primary, cache_origin)
        if shadow is not None:
            _run_shadow_comparison(ParseRule.PROGRAM, source, primary, shadow, node, None)
    return cast("ast.Program", node)
