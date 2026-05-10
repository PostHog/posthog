# hogql_visitors_rs (PoC)

PoC exploring whether moving HogQL AST visitors to Rust meaningfully cuts the
"accumulated slowdown from adding more and more visitors" that Marius flagged
in [#58186](https://github.com/PostHog/posthog/pull/58186).

This crate isn't wired into anything in production. It exists to make the
performance trade-offs concrete before we commit to a direction.

## What's measured

`HogQLFeatureExtractor` is the simplest non-trivial visitor we have, so it
makes a clean A/B subject. Three implementations:

| Variant                                 | What it does                                                                                                                   |
| --------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| Python (current)                        | `posthog/hogql/feature_extractor.py` — `TraversingVisitor` subclass                                                            |
| `extract_features_py` (Rust, A)         | Reads Python AST objects in place via PyO3. Same per-node Python C-API cost as Python, but skips interpreter dispatch overhead |
| `extract_features_via_mirror` (Rust, B) | Walks the Python AST once to build a Rust-native enum, then walks the enum natively                                            |

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

## Expected speedup (and the catch)

Local baseline on the existing Python visitor (`bench_visitor.py` in this
PR's history):

```text
query                         nodes     µs/run    ns/node
tiny                              2       2.64     1322.1
events_simple                     7       7.14     1019.6
events_in_clause                 10       9.44      943.7
join_persons                     13      12.03      925.0
subquery_with_filters            34      24.78      728.7
trends_like_breakdown            53      37.20      702.0
```

So Python sits at ~700–1300 ns/node. PyO3-from-Rust attribute lookups are
~200–400 ns each, and a typical visit step does several. Realistic numbers
for the two strategies, based on PyO3 microbenchmarks I'd expect to roughly
hold here:

- **Strategy A** (read Python in place): ~2–3× faster than Python. The wins
  come from skipping the `node.accept(self) → self.visit_X(node)` dispatch
  and from inlined `cls.name` checks instead of `isinstance`.
- **Strategy B** (convert + walk native): ~0.7–1× for _one_ visitor (the
  conversion costs as much as the walk it replaces). For _N_ visitors that
  share the converted tree, each additional visitor is essentially free
  (~10–100× faster than Python). Break-even is around 2 visitors.

The reason "minimal interop cost" isn't quite the whole story: every Python
attribute access from Rust still goes through CPython's C API — type-check,
dict lookup, refcount bump. PyO3 wraps this neatly, but doesn't shortcut it.
Returning a list of strings is cheap; _reading_ a deep Python tree isn't.

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

Output columns: Python, Rust-A (read Python), Rust-B (convert+walk),
Rust-B-amortised-over-5-visitors.
