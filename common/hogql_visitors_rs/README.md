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
| `extract_features_via_mirror_fast` (Rust, B-fast)      | Same as B but with the A-fast tricks (interned attribute names, cached type pointers) applied to the conversion pass.                  |
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
query                    python      A   A-fast   B-fast: full   B: visit   B-fast: convert
tiny                      12.46   1.07     0.61           0.61       0.42              0.19
events_simple             33.08   4.47     2.42           3.49       1.13              2.36
events_in_clause          44.78   5.49     3.18           4.92       1.64              3.28
join_persons              56.26   5.36     2.94           4.75       1.34              3.41
subquery_with_filters    120.80   6.93     3.21           6.65       0.84              5.80
trends_like_breakdown    180.81   7.36     3.50           6.02       0.84              5.18
pathological_deep       1182.35   5.28     2.76           8.72       0.82              7.90
```

(The full bench output includes "plain B" columns too — same shape, just
~1.7–1.8× slower than B-fast in every cell that depends on conversion.)

`pathological_deep` is a synthetic 361-AST-node query — multi-CTE, nested
UNION ALL branches, multi-join — shaped after a complex insight. The row
is the most compelling argument for Rust here: **Python spends 240 µs per
call** on that shape; Rust-A finishes in ~1 µs. ~243× speedup, and A is
actually _faster_ than its smaller-query numbers because the targeted
visitor only recurses where it needs to, while Python's TraversingVisitor
base walks every child of every node.

**A-fast** and **B-fast** are A and B plus two cheap tricks that exploit
the fact that we know the AST shape ahead of time: PyO3's `intern!`
caches the attribute-name PyStrings so subsequent `getattr` calls skip
the hash, and the AST class type objects are cached at first use so
dispatch becomes a pointer comparison via `is_exact_instance` instead
of pulling out a class-name string and comparing it.

The win:

- **A-fast** is 1.7–2.2× over plain A. On the trends-like query that's
  ~54× vs Python; on `pathological_deep` ~389×.
- **B-fast's `convert`** is 1.7–1.8× over plain B's convert, dragging
  B-fast's full cost down with it.
- The native walk (`B: visit`) is unchanged — already pure Rust.

On small queries A-fast is essentially as fast as B's pure-native walk;
the gap reopens on big queries because A-fast still pays one (now-cheap)
PyO3 attribute access per node it visits, while B's native walk is
walking native enum variants with zero CPython crossings.

What the split makes obvious:

- **A-fast (read Python in place)** is a great single-visitor port —
  ~50× faster than Python on the trends-like query.
- **B's `convert` step dominates B's total** — and the same intern +
  cached-type-pointer tricks shave ~1.7–1.8× off it, dragging B-fast
  full cost down too.
- **B's `visit only` step is essentially free** — under 1 ms for 5000
  walks of the trends-like query. Pure native-tree-walk cost; unaffected
  by the fast tricks because there's no PyO3 work in it.

For one visitor over a query, A-fast wins. For multiple visitors over
the same query, B-fast's "pay one cheap convert, run N essentially-free
walks" wins fast — break-even vs A-fast is ~2 visitors on the trends-like
query, and at 5 visitors B-fast is ~1.9× faster than A-fast and ~96×
faster than Python.

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
