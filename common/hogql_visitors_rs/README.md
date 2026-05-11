# hogql_visitors_rs (PoC)

PoC exploring whether moving HogQL AST visitors to Rust meaningfully cuts the
"accumulated slowdown from adding more and more visitors" that Marius flagged
in [#58186](https://github.com/PostHog/posthog/pull/58186).

This crate isn't wired into anything in production. It exists to make the
performance trade-offs concrete before we commit to a direction.

## What's measured

`HogQLFeatureExtractor` is the simplest non-trivial visitor we have, so it
makes a clean A/B subject. Three implementations:

| Variant                                                | What it does                                                                                                                           |
| ------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------- |
| Python (current)                                       | `posthog/hogql/feature_extractor.py` — `TraversingVisitor` subclass                                                                    |
| `extract_features_py` (Rust, A)                        | Reads Python AST objects in place via PyO3. Same per-node Python C-API cost as Python, but skips interpreter dispatch overhead         |
| `extract_features_py_fast` (Rust, A-fast)              | Same as A, but with PyO3 `intern!`'d attribute names and cached AST class type pointers. Dispatch becomes pointer compare, not strcmp. |
| `extract_features_via_mirror` (Rust, B, full)          | Walks the Python AST once to build a Rust-native enum, then walks the enum natively. Both phases on every call.                        |
| `to_mirror` + `extract_features_from_mirror` (B split) | Exposes the convert and visit phases separately so the bench can measure them independently                                            |

Strategy A has a flat-ish per-call cost. Strategy B has a high one-time cost
(the conversion) plus a near-zero per-pass cost — so the win shows up only
when several visitors share the same converted tree.

## Build process

The crate uses [PyO3](https://pyo3.rs) (Rust ↔ Python bindings) and
[maturin](https://www.maturin.rs/) (build backend that produces the same
shape of Python wheel `setuptools` would).

`pip install`-style integration during development:

```bash
# from common/hogql_visitors_rs/
maturin develop --release
```

That builds the `cdylib`, drops it as `hogql_visitors_rs.<abi>.so` into the
active venv's `site-packages`, and you can `import hogql_visitors_rs` from
Python with no extra glue.

For a release wheel:

```bash
maturin build --release
# → target/wheels/hogql_visitors_rs-0.1.0-cp312-abi3-*.whl
```

The `abi3-py312` feature in `Cargo.toml` means one wheel covers Python 3.12+,
so we don't need a per-minor-version build matrix.

In the existing monorepo, the analogous setup is `common/hogql_parser/`,
which uses `setup.py` + a C++ extension. That predates Rust adoption in the
repo. The `funnel-udf/` crate is pure Rust (no Python bindings) and `rust/`
is the production Rust services. Adding `cdylib` + `pyo3` here is a new
integration shape, but mechanically the wheel-building story is the same as
`hogql_parser`'s — the build step just lives in a different toolchain.

CI integration would look like: a new Depot-runner job that runs
`maturin build --release` into a wheel, and the existing Python wheel
publishing flow consumes it. For local dev `maturin develop` keeps it cheap.

## Measured speedup

Numbers from `bench/compare.py` on Apple Silicon, release build, **total ms
for 5000 invocations** of each variant. B is split into `convert`
(Python → Rust mirror) and `visit only` (walking the converted mirror) so
the conversion overhead is visible separately from the visitor cost.

```text
query                    python      A   A-fast   B: full   B: visit only   B: convert
tiny                      12.37   1.14     0.60      1.11            0.42         0.70
events_simple             32.85   4.61     2.51      5.43            1.18         4.25
events_in_clause          44.27   5.76     3.21      7.13            1.59         5.54
join_persons              55.64   5.24     2.84      6.72            1.35         5.37
subquery_with_filters    119.68   6.15     3.05     10.41            0.79         9.62
trends_like_breakdown    179.76   7.24     3.33      9.86            0.81         9.05
pathological_deep       1207.06   5.19     3.10     13.48            0.75        12.73
```

`pathological_deep` is a synthetic 361-AST-node query — multi-CTE, nested
UNION ALL branches, multi-join — shaped after a complex insight. The row
is the most compelling argument for Rust here: **Python spends 240 µs per
call** on that shape; Rust-A finishes in ~1 µs. ~243× speedup, and A is
actually _faster_ than its smaller-query numbers because the targeted
visitor only recurses where it needs to, while Python's TraversingVisitor
base walks every child of every node.

**A-fast** is A plus two cheap tricks: PyO3's `intern!` caches the
attribute-name strings so subsequent `getattr` calls skip the hash, and
the AST class types are cached at first use so dispatch becomes a pointer
comparison via `is_exact_instance` instead of pulling out a class-name
string and comparing it. Net: another 1.7–2.2× over A across the board,
or ~54× vs Python on the trends-like query, ~389× on pathological_deep.
On small queries it's essentially as fast as B's pure-native walk; the
gap reopens on big queries because A-fast still pays one (now-cheap)
PyO3 attribute access per node it visits, while B's native walk is
walking native enum variants.

What the split makes obvious:

- **A (read Python in place)** is a great single-visitor port — 8–25×
  faster than Python on its own.
- **B's `convert` step dominates B's total**, ~85–90% of the cost. Each
  conversion does the same Python `getattr` work A does, plus allocates
  Rust enum nodes.
- **B's `visit only` step is essentially free** — <1.5 ms for 5000 walks
  of the trends-like query, vs ~7 ms for A on the same workload. This is
  the pure native-tree-walk cost.

That last row is the punchline. For one visitor over a query, A wins. For
multiple visitors over the same query, B's "pay convert once, run N cheap
walks" wins fast — break-even is ~1.5 visitors on the trends-like query,
and at 5 visitors B is ~2.7× faster than A and ~67× faster than Python.

The "minimal interop cost" hypothesis worked out better than I expected:
yes, every Python attribute access from Rust still goes through CPython's
C API, but Python's interpreter overhead per method call (frame setup,
dict lookup for visitor dispatch, isinstance MRO walk) is roughly an
order of magnitude heavier than the single C call PyO3 makes. Net: even
a single-visitor Rust port is very much worth it; the multi-visitor batch
API is icing on top.

## What this points toward (if we like the numbers)

The architectural punchline is in Marius's framing: it's the _number_ of
visitors that hurts, not any single one. So the bigger win is a batch API
that runs many visitors over one converted AST:

```python
# notional API
features, workload, has_lazy_joins = batch_visit(
    parsed,
    [FeatureExtractor(), WorkloadCollector(), LazyJoinDetector()],
)
```

In the current `prepare_ast_for_printing` pipeline we run Resolver +
WorkloadCollector + (during PR #58186) FeatureExtractor + the printer pass —
each its own deep walk. Bundling those into one Rust-side traversal is where
the "accumulated slowdown" claim genuinely flips.

That's a much bigger lift than this PoC: it'd mean either
(a) building enough of a Rust-native AST mirror to host _all_ visitors, or
(b) making the resolver / printer Rust-native too and keeping the AST as
the canonical representation.

Likely sequencing if we want to commit to this:

1. Land this PoC behind a feature flag, measure it on a few specific
   visitors with high call volume (workload detection is the obvious next
   candidate — runs on every printed query).
2. Stand up the batch API in Rust with two or three visitors.
3. Decide based on observed cumulative-time numbers whether to go further.

## Running the benchmark

```bash
cd common/hogql_visitors_rs
maturin develop --release
cd ../..
python common/hogql_visitors_rs/bench/compare.py
```

Output columns: Python (current), Rust-A (read Python in place), Rust
A-fast (A + interned attribute names + cached type pointers), Rust-B
full (convert + walk on every call), Rust-B visit-only (walk a
pre-converted mirror), Rust-B convert (the leftover, i.e. the cost
amortised when reused across multiple visitors).
