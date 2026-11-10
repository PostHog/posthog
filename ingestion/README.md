# Ingestion

The ingestion team's services live under this directory: the Rust crates, the Node packages, their protos, their CI and images, and pinned copies of the few outside format files they read.

## Rules

1. **Location follows layer, ownership follows `owners.yaml`.** Generic infrastructure lives in common (`rust/common/*`, the shared Node packages); ingestion's product code lives here. Another team's product code does not live here even when ingestion runs it.
2. **Direction.** Ingestion depends on common and on nothing else outside this tree. Other teams depend on ingestion only through its contract crates and packages, never on its pipelines or servers.
3. **Path dependencies, one workspace per language.** The Rust crates are members of the `rust/` workspace and the Node packages of the root pnpm workspace. Nothing is copied. A pin, a published version or a copy under `pinned/` with a `SOURCE.json`, is used for another team's product that ingestion embeds at that team's cadence, and for format files from another tree. Every pin is listed in `pinned/` with its reason.
4. **Lanes come from the dependency graph.** A change claims the merge queue lanes of the servers and crates that run it, computed from imports and from the cargo determinator, so a file outside this tree claims an ingestion lane only when ingestion actually runs it. A change the graph cannot place claims every lane except ingestion's; the only exception is the short list of root files every Node package builds from (`INGESTION_ROOT_BUILD_INPUTS` in the lane script, held equal to `ingestion-node.yml`'s filter by a test), which claim ingestion's lanes too.

## Layout

```text
ingestion/
  rust/      ingestion's crates, members of the rust/ workspace (each declares workspace = "../../../rust")
  node/      ingestion's Node packages: packages/common (@posthog/ingestion-common, the contract other services import)
             packages/ingestion (@posthog/ingestion, the pipelines and servers) and packages/ai-research
             (@posthog/ingestion-ai-research, the AI research team's pipelines and servers, their own lane and image)
  proto/     the protos ingestion owns
  pinned/    copies of outside format files, each with a SOURCE.json
  ci/        compose stack, determinator rules, image list, scripts and composite actions the workflows use
```

## Working here

- Run cargo from `rust/`, the workspace root: `cargo test -p capture`. Cargo also resolves the workspace from inside a crate directory; `ingestion/rust/.cargo/config.toml` links to the workspace's build config so it applies there too.
- `ingestion-rust.yml` decides what to build with `rust/affected-services --rules ingestion/ci/determinator-rules.toml`, so a change to `rust/common` runs exactly the ingestion crates that depend on it.
- The images build from the repository root with `rust/Dockerfile` and `ingestion/node/Dockerfile`; `ingestion/ci/images.yml` lists them.
- The CI stack's ClickHouse mounts Django's user-defined functions from the checkout (`docker/clickhouse/user_defined_function.xml`, `posthog/user_scripts`), because the pinned schema's materialized views call them and the executables are too large to pin.
- The hog engine is CDP's: `publish-hog-engine-npm.yml` publishes `@posthog/hog-engine` from master and `bump-hog-engine.yml` opens the PR that moves ingestion's pin. The pin replaces the `workspace:*` dependency in `packages/ingestion/package.json` once the first version is on npm.
