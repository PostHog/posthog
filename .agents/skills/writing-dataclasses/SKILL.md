---
name: writing-dataclasses
description: >
  House rules for Python dataclasses in PostHog: when to reach for one instead of a tuple or `dict[str, Any]`, which decorator to use (`@frozen` from `posthog.dataclasses`), how to name, construct, consume and evolve them, how to keep secrets out of `repr`, and when a function should accept a dataclass instead of its unpacked fields.
  Use when adding or changing a dataclass, returning or passing several values from a function, converting a tuple or dict payload, deciding `frozen=`/`slots=`/`kw_only=`, or passing a facade contract DTO through internal layers.
  Not for pydantic models used as HogQL/query schema, DRF serializers, or Django models.
---

# Writing dataclasses

The point of every rule here is the same: values that share a type get swapped silently, and a positional tuple or a `dict[str, Any]` lets that happen. A named, frozen dataclass makes the swap a typecheck failure instead of a runtime bug. Everything below follows from that; if a rule doesn't serve it in your case, say so in the PR and skip it.

## When a dataclass, when not

- **Return or pass a dataclass instead of a tuple** when two or more elements share a type (`(start, end)`, `(width, height)`, `(rows, columns)`), or when the tuple has roughly 3+ elements and positional access hurts readability. A small tuple of clearly different types (`(user, count)`) is fine as-is.
- **Prefer a dataclass over `dict[str, Any]`** when a fixed set of values crosses a function boundary. A dict key typo fails at runtime; a dataclass field typo fails typecheck. Dicts stay for genuinely dynamic key sets.
- **`NamedTuple` is not the answer** for the swap problem: it still unpacks positionally.

## Which decorator

Use `@frozen` from `posthog.dataclasses` for internal value and result objects. It is `@dataclass` with `frozen=True, kw_only=True, slots=True` as defaults, and every flag is overridable:

```python
from posthog.dataclasses import frozen

@frozen
class BillingPeriod:
    start: datetime
    end: datetime

@frozen(slots=False)          # class uses functools.cached_property
class ParsedQuery: ...

@frozen(frozen=False)         # genuinely mutated after construction (a builder, an accumulator)
class RunAccumulator: ...
```

- `kw_only=True` is what actually prevents swaps at construction: `BillingPeriod(start=a, end=b)`, never `BillingPeriod(a, b)`. Don't override it without a reason.
- `slots=True` blocks `functools.cached_property` and ad-hoc attributes; override with `slots=False` rather than dropping `@frozen`.
- A bare `@dataclass` with no explicit `frozen=` fails the ratchet in `posthog/test/repo_invariants/test_dataclass_defaults.py` and is flagged by the advisory `prefer-frozen-dataclasses` semgrep rule. `@dataclass(frozen=False)` passes; the ratchet asks for a stated choice, not immutability. If you only _moved_ an existing bare `@dataclass`, regenerate the baseline with `python posthog/test/repo_invariants/test_dataclass_defaults.py` instead of decorating it.
- Don't add `frozen=False` to a bare `@dataclass` you didn't otherwise touch. The ratchet counts per file against a baseline; an unchanged count passes, and the edit is churn in someone else's file.
- Facade contracts (`products/<name>/backend/facade/contracts.py`) are frozen dataclasses too, usually `pydantic.dataclasses.dataclass(frozen=True)` so they validate on construction. See [products/architecture.md](../../../products/architecture.md).

## Naming

Name the class after the domain concept, not the plumbing: `ClickHouseCredentials`, `BillingPeriod`, `SnapshotManifestItem`. `*Result` only when the function's outcome genuinely is the concept; never `*Info`, `*Data`, `*Tuple`, `*Response` for an internal object. Underscore-prefix classes private to one module.

## Constructing and enforcing invariants

- Enforce invariants in `__post_init__` (`start <= end`, exactly one auth method set, value in range) so an invalid instance fails at construction rather than deep in later logic. On a frozen class use `object.__setattr__` only if you must normalize; prefer raising.
- Type a field holding a closed set of strings as `Literal[...]` or an enum, not bare `str`. Check call sites: narrowing an existing field can surface mypy errors where callers pass a plain `str`; fix the callers, don't widen the field back.
- A frozen dataclass hashes, so use a small keyed class as a dict or set key instead of a tuple when the key has two or more same-typed parts.

## Consuming and evolving

- Read fields with dot notation (`result.start`). Never `a, b = result.a, result.b` into positional locals; that reintroduces the swap.
- Evolve a frozen instance with `dataclasses.replace(instance, field=value)`, not by copying fields by hand.
- Dispatch on variants with `match`/`case` (`case BinaryOp(left=left, right=right):`) when there are several; a single-type check stays a plain `isinstance` guard.

## Secrets

Mark secret fields with `field(repr=False)` so they cannot leak through `repr()` into tracebacks and logs, and never `asdict()` such a dataclass into log output, which reintroduces what `repr=False` hides.

## Passing a dataclass through layers

When a function's parameters mirror the fields of a dataclass the caller already holds, accept the dataclass instead of the unpacked fields. That stops same-typed positionals being threaded through several layers, and it is Fowler's Preserve Whole Object.

Three carve-outs, in priority order:

1. **Invariants win over mirroring.** Never pass a wider type into a callee that needs a narrower one. If the dataclass has `url: str | None` and the helper needs a `str`, keep the `str` parameter (or narrow the type at the boundary); do not accept the dataclass and add a runtime `ValueError`. That trades a typecheck for a guard clause, which is the opposite of the point.
2. **Wire signatures keep their shape.** Temporal `@activity.defn`/`@workflow.run` and celery task boundaries take what they take; the helper behind them accepts the dataclass.
3. **Facade contracts that are also request bodies are wire signatures too.** A contract in `facade/contracts.py` backed by `DataclassSerializer` and `@validated_request` is the HTTP body, the OpenAPI schema, and the shape shipped clients send. A product's `logic` may accept its own contract while the fields are one-to-one with what logic needs; do not pre-emptively build a parallel internal DTO. Split into an internal parameter object at the first real divergence: the wire carries dead or deprecated fields logic ignores, logic needs values the wire must not accept, or logic needs an invariant the wire can't promise. The split lives in `facade/api.py`, the only in-process caller.

## What enforces this

- `posthog/test/repo_invariants/test_dataclass_defaults.py` (blocking ratchet): new bare `@dataclass` without `frozen=`.
- `.semgrep/rules/devex/prefer-frozen-dataclasses.yaml` and `tuple-return-prefer-dataclass.yaml` (advisory).
- Everything else is review.
