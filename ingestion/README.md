# Ingestion

Everything the ingestion team owns and builds lives under this directory: the Rust services, the Node pipelines, their protos, their CI, and the pinned copies of the few outside files they read.

The directory exists so that a change outside it can never affect ingestion's tests or its merge queue lane. That property rests on six rules.

## Rules

1. **One directory.** Ingestion's code, build files and CI live here. The only exception is the workflow files, which GitHub requires under `.github/workflows/`; ingestion's are named `ingestion-*.yml`, and the reusable ones `_ingestion-*.yml`.
2. **Nothing crosses the boundary as source.** No file under `ingestion/` imports, extends, depends on or mounts a path outside it, and nothing outside depends on a path inside it.
3. **What must cross is pinned to a version.** A library crosses as a published package. A format file, such as schema SQL or a proto, crosses as a copy under `pinned/` with a `SOURCE.json` that records its origin and checksums.
4. **A bump is an ingestion PR.** Raising a package version or refreshing a pinned copy is a change under `ingestion/`, so it runs ingestion's tests and sits in ingestion's lane.
5. **The checkout is the proof.** Every job in the ingestion workflows checks out only `ingestion/`. A job cannot be affected by a file it never downloads.
6. **One lane rule.** Only paths under `ingestion/` and the `ingestion-*.yml` workflows map to the lane targets of the packages here. The every-lane set in the merge queue rules never includes them.

## Layout

```text
ingestion/
  rust/      the cargo workspace: services, shared crates, Dockerfile
  node/      the pnpm workspace: the ingestion package, with the AI research pipelines beside it
  proto/     the protos ingestion owns
  pinned/    copies of outside format files, each with a SOURCE.json
  ci/        compose stack, service configs, scripts and composite actions the workflows use
```

## Working here

- Run Rust tooling from `ingestion/rust` and Node tooling from `ingestion/node`. Each has its own lockfile.
- A shared helper that ingestion needs is copied here and owned here. A library that other teams build on is published from here and consumed by version.
- The AI research pipelines are owned by the AI research team. They depend on ingestion by workspace path and have a merge queue lane of their own.
