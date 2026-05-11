# hogql_visitors_rs (PoC)

PoC exploring whether moving HogQL AST visitors to Rust meaningfully cuts the
"accumulated slowdown from adding more and more visitors" that Marius flagged
in [#58186](https://github.com/PostHog/posthog/pull/58186).

This crate isn't wired into anything in production. It exists to make the
performance trade-offs concrete before we commit to a direction.

## What's measured

`HogQLFeatureExtractor` is the simplest non-trivial visitor we have, so it
makes a clean A/B subject. Three implementations:

| Variant                                                                      | What it does                                                                                                                                                                                                                                                 |
| ---------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Python (current)                                                             | `posthog/hogql/feature_extractor.py` — `TraversingVisitor` subclass                                                                                                                                                                                          |
| `extract_features_py`                                                        | Rust strategy A: walks Python AST objects in place via PyO3 with interned attribute names + cached AST class type pointers (`is_exact_instance`).                                                                                                            |
| `extract_features_py_slots`                                                  | Rust strategy A-slots: same as A but reads each AST field via the cached `__slots__` C offset, bypassing `getattr`'s MRO walk and descriptor invocation. ~30 lines of `unsafe` to extract the offset from each slot's `member_descriptor` once at first use. |
| `extract_features_via_mirror` + `to_mirror` / `extract_features_from_mirror` | Rust strategy B: converts the Python AST to a Rust-native enum once, then walks the enum natively. Split API so the bench can measure convert vs visit independently.                                                                                        |

This branch also adds `slots=True` to every `@dataclass` in
`posthog/hogql/{ast.py, base.py}` — the AST has no external subclasses,
no `setattr` of ad-hoc fields, no `__dict__` reads, and no weakrefs, so
the conversion is contained.

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

Numbers from `bench/compare.py` on Apple Silicon, release build. The
`python (orig)` column is from a separate run on the same machine
with `slots=True` reverted, so the slots-only win is isolable.

```text
query                    py(orig)  py(+slots)  py(now)      A   A-slots   B: full   B: convert   B: visit
tiny                        17.64       12.12     6.07   0.60      0.44      0.63         0.21       0.42
events_simple               34.66       32.17    12.76   2.46      1.77      3.93         2.81       1.12
events_in_clause            46.27       43.64    16.69   3.20      2.40      4.92         3.37       1.56
join_persons                57.26       55.21    19.05   2.97      1.87      4.46         3.18       1.28
subquery_with_filters      123.74      116.04    30.31   3.21      2.01      6.32         5.50       0.82
trends_like_breakdown      189.15      175.58    43.69   3.40      2.14      6.07         5.28       0.80
pathological_deep         1215.99     1170.69   277.89   3.00      2.07      9.00         8.21       0.79
```

(`py(now)` = `__slots__` on the AST + cached `accept()` method-name dispatch.)

(All numbers in ms total for 5000 invocations.)

`pathological_deep` is a synthetic 361-AST-node query — multi-CTE,
nested UNION ALL branches, multi-join — shaped after a complex insight.
The row is the headline: with both Python optimisations applied, the
visitor goes from ~243 µs/call (original) to ~57 µs/call (~4× faster
without leaving Python), and Rust-A finishes the same work in ~0.6 µs
(~410× vs the original).

What the columns tell us:

- **`py(orig)` → `py(+slots)`** is the free win from declaring
  `__slots__` on the AST. Smaller than I'd hoped — roughly 4–8% across
  the board. Most of the visitor's cost wasn't in field access.
- **`py(+slots)` → `py(+slots, +cached)`** is the much bigger Python
  win: caching `accept()`'s method-name computation on the class via
  `__init_subclass__`. The original `AST.accept` ran a regex sub, four
  `str.replace` calls, and an f-string on every single node visit —
  pure dispatch overhead that doesn't depend on what the visitor
  actually does. Computing the method name once at class creation and
  reading it back as a plain class attribute gets us **3–4× over the
  slots-only number**. On `pathological_deep` that's 1170 ms → 286 ms.
- **Strategy A** is the right choice for one-off visitors. Walks Python
  in place via PyO3 with interned attribute names and cached AST class
  type pointers; dispatch is `is_exact_instance(&cached_type)` not
  string compare. ~5–10× faster than the optimised Python on
  small/medium queries, and stretches to **~93×** on
  `pathological_deep` because the targeted visitor doesn't recurse
  where it doesn't need to.
- **Strategy A-slots** is A plus direct slot-offset reads. PyO3's
  `getattr` still walks the MRO + invokes the slot descriptor; once we
  cache each slot's C offset (via ~30 lines of `unsafe` reading the
  `member_descriptor`'s `PyMemberDef`), reads become raw pointer
  arithmetic + load + incref. **1.3–1.6× faster than plain A** across
  the board, taking pathological from ~93× to ~135× vs Python.
  Downside: tied to CPython's `PyMemberDescrObject` layout, stable for
  3.12+ but technically internal. A trapdoor we'd want behind a
  feature flag rather than a default.
- **Strategy B's `convert` step dominates B's total**, ~85–90% of the
  cost. Each conversion does the same Python `getattr` work A does,
  plus allocates Rust enum nodes.
- **Strategy B's `visit only` is essentially free** — under 1 ms for
  5000 walks of the trends-like or pathological queries. Pure native
  walk, no PyO3 in the inner loop.

For one visitor over a query, A wins. For multiple visitors over the
same query, B's "convert once, run N cheap walks" wins fast — break-even
vs A is ~2 visitors on the trends-like query; at 5 visitors B is ~2×
faster than A.

The "minimal interop cost" hypothesis worked out better than I expected:
yes, every Python attribute access from Rust still goes through CPython's
C API, but Python's interpreter overhead per method call (frame setup,
dict lookup for visitor dispatch, isinstance MRO walk, regex'd name
formatting in `accept`) is roughly an order of magnitude heavier than
the single C call PyO3 makes. Net: even a single-visitor Rust port is
very much worth it; the multi-visitor batch API is icing on top.

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
