---
name: changing-hogvm
description: How to change the HogVM without breaking cross-language parity. Use for any change under common/hogvm/ or rust/common/hogvm/ - adding or removing an STL builtin, changing a function's arity (minArgs/maxArgs) or behavior, changing VM error messages, editing spec/stl.json, the conformance vectors, or the shared test corpus. Covers the spec-as-source-of-truth workflow (edit the JSON, run the compiler, never hand-edit generated artifacts), the rule that behavior lands in Python, TypeScript, and Rust together, and which CI gates enforce each part. Trigger terms - hogvm, Hog VM, STL, builtin, arity, stl.json, execute.py, execute.ts, hogvm corpus, hogvm parity.
---

# Changing the HogVM

The HogVM runs Hog bytecode in three languages that must behave identically: Python
(`common/hogvm/python/`, the reference), TypeScript (`common/hogvm/typescript/`, published as
`@posthog/hogvm`), and Rust (`rust/common/hogvm/`, the production node path via
`@posthog/hogvm-node`). A change that lands in one VM and not the others is a parity bug that
surfaces as customer-visible behavior differences between products.

## The contract: spec/stl.json is the only source of truth for the STL surface

`common/hogvm/spec/stl.json` declares every builtin with its accepted argument counts
(`minArgs`/`maxArgs`, `null` = unbounded) and, for the few partial functions, which VMs implement
it. The VMs consume it — Python loads the JSON at import; TypeScript and Rust consume generated
artifacts. Consequences:

- **Never declare arity in a VM.** There is nowhere to put it: the Python `STLFunction(...)`
  entries and TS `STL` records carry no `minArgs`/`maxArgs` (a semgrep rule rejects re-adding
  them), and the values are applied from the spec at import.
- **Never hand-edit the generated files** — `typescript/src/stl/stlSpec.ts`,
  `rust/common/hogvm/src/stl_spec.rs`, `spec/vectors/arity.json`. CI regenerates them and fails
  on any diff.
- To change the surface, edit `spec/stl.json` and regenerate:

```bash
python -m common.hogvm.spec.compile
```

## Recipes

### Changing a function's arity

Edit its `minArgs`/`maxArgs` in `spec/stl.json`, run the compiler, commit the JSON plus the three
regenerated artifacts. All three VMs pick the change up with no code edits. Check
`docs/internal/hog-function-arities.md` first — several arities are deliberately wider or narrower
than HogQL's, and HogQL compatibility is tested by
`posthog/hogql/functions/test/test_hog_stl_arity.py`.

### Adding a builtin

1. Implement it in **all three VMs**: `common/hogvm/python/stl/__init__.py`,
   `common/hogvm/typescript/src/stl/stl.ts`, and `rust/common/hogvm/src/stl.rs`. A function
   implemented in fewer VMs needs an `implementations` key in its spec entry **and** an update to
   the partial-implementations ratchet test in `common/hogvm/python/test/test_stl_spec.py` —
   growing that list forks the surface, so treat it as a last resort and say why in the PR.
2. Add the spec entry and run the compiler. A builtin missing from the spec fails the Python STL
   at import and throws at TS module init, so you cannot forget this step.
3. Cover the behavior: a corpus program under `common/hogvm/__tests__/` for printable behavior
   (run `./common/hogvm/test.sh <name>.hog` to generate snapshots), or a hand-written vector in
   `spec/vectors/` for result/error behavior. Arity-error vectors are generated — do not write
   them by hand.
4. Bump `typescript/package.json` and add a `common/hogvm/CHANGELOG.md` entry — merging a version
   change publishes `@posthog/hogvm` to npm.

### Changing behavior or error messages

Change all three VMs in the same PR. Regenerate corpus snapshots with `./common/hogvm/test.sh`
(it diffs Node, compiled JS, and Python against each other and rewrites
`__tests__/__snapshots__/`), and expect the Rust gates to hold you to the new snapshots. Arity
error messages are pinned byte-for-byte by the vectors in all three languages — the shared format
is `Function <name> requires at least|at most N arguments`.

### Removing a builtin

Remove it from all three VMs and from `spec/stl.json`, regenerate, and treat it as a breaking
change in the CHANGELOG — saved Hog programs may call it.

## Verify before pushing

```bash
python -m common.hogvm.spec.compile && git diff --exit-code   # artifacts fresh
python -m pytest common/hogvm                                  # python + vectors + ratchets
pnpm --filter=@posthog/hogvm test                              # typescript + vectors
cargo test -p hogvm --manifest-path rust/Cargo.toml            # rust corpus/oracle/vector gates
./common/hogvm/test.sh                                         # cross-VM corpus (regenerates snapshots)
```

## How CI enforces this

- **ci-hog** (on `common/hogvm/**`): spec-artifact freshness check, Python and TS suites, and
  `test.sh` with `git diff --exit-code` over the snapshots.
- **ci-rust** (also triggered by `common/hogvm/**` via its paths filter and
  `rust/affected-services/determinator-rules.toml`): the Rust crate's corpus parity report
  (`tests/parity.rs`, diffs against the committed Node snapshots), the per-STL oracle
  (`tests/stl_parity.rs`), the spec vectors, and the contract-table agreement test.
- **semgrep-devex**: rejects `minArgs=`/`maxArgs:` declarations reappearing in VM code.
