# kea-wasm

An experimental drop-in replacement for `kea@4.0.0-pre.6` whose engine is written in Rust and compiled to WebAssembly.
It exists to measure whether moving kea's bookkeeping out of JavaScript makes the app faster.
It is opt-in through `KEA_IMPL=wasm`. Without the flag, every build and test uses the normal `kea` package.

## What runs in Rust

`crate/src/lib.rs` owns:

- the reducer tree (`attachReducer`, `detachReducer`, `regenerateRootReducer`, the whitelist),
- the combined root reducer and each logic's `combineKeaReducers(logic.reducers)`, which run on every dispatch,
- mount reference counts (`context.mount.counter`),
- the listener index (`byAction`, `byPath`) and the listeners middleware loop,
- action type names (`createActionType`).

The JavaScript shell in `src/` is the kea source with those parts replaced.
Logic objects, selectors (reselect), React hooks and plugin events stay in JavaScript, because user code holds and mutates them.

### Incremental reducers

Kea calls every reducer of every mounted logic on every dispatch, and it rebuilds the whole reducer tree on every mount.
The engine does less work and gives the same results:

- Each compiled node knows the action types that can change it.
  If a node receives the same state object that it returned last time, and the action can not change it, it returns that state without a call into JavaScript.
- Reducers that kea did not generate (for example kea-localstorage wrappers, or plain redux reducers) are opaque.
  A subtree with an opaque reducer always runs.
- `logic.reducers`, `logic.actionKeys` and `logic.defaults` are proxies, so a plugin or `logic.extend()` that changes them after mount invalidates the cached results.
- Mounts and unmounts recompile only the changed path. Subtrees with empty nodes are rebuilt, so the identity of their empty state objects changes exactly as in kea.

Internal fields that tests and plugins read (`context.reducers.tree`, `context.mount.counter`, the listeners plugin context) are getters over the engine.
`context.reducers.tree` also accepts writes.

## Build

Needs Rust with the `wasm32-unknown-unknown` target and `wasm-bindgen-cli` 0.2.100.

```bash
rustup target add wasm32-unknown-unknown
```

```bash
cargo install wasm-bindgen-cli --version 0.2.100
```

```bash
node packages/kea-wasm/build.mjs
```

The build embeds the module as base64 and instantiates it synchronously, because kea opens its default context at import time.
The package is not a pnpm workspace member. `build.mjs` bundles the same redux, reselect and use-sync-external-store copies that kea resolves, and leaves React to the consumer.

## Use it in the app

Set `KEA_IMPL=wasm` for the esbuild build (`common/esbuilder`), Vite, Storybook or Jest:

```bash
KEA_IMPL=wasm pnpm --filter=@posthog/frontend start
```

```bash
cd frontend && KEA_IMPL=wasm npx jest src/scenes/insights/insightLogic.test.ts
```

## Tests

- `test/jest/` is kea's own jest suite, copied from keajs/kea (MIT, see `KEA_LICENSE.md`).
- `test/differential/` runs random scenarios against kea and kea-wasm and compares state, changed subtree identities, user reducer and listener calls, and errors after every step.

```bash
cd frontend && npx jest --config ../packages/kea-wasm/jest.config.cjs
```

```bash
cd frontend && KEA_TEST_TARGET=original npx jest --config ../packages/kea-wasm/jest.config.cjs
```

`snapshot.js` needs `react-test-renderer`, which the repo does not install. Point `KEA_TEST_EXTRA_MODULES` at a `node_modules` directory that has it.

```bash
cargo test --manifest-path packages/kea-wasm/crate/Cargo.toml
```

## Benchmark

```bash
node packages/kea-wasm/bench/engine-bench.cjs js 50 200 800
```

```bash
node packages/kea-wasm/bench/engine-bench.cjs wasm 50 200 800
```
