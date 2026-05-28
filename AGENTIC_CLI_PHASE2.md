# Agentic CLI — Phase 2 (started): per-category commands

Phase 1 gave a generated, parity-verified manifest + interpreter, exercised via the raw
`posthog-cli exp agent run <tool> --json '...'`. Phase 2 adds the **native command UX**: grouped
commands with real flags and auto-generated help.

## What works now

```bash
posthog-cli feature-flag create --key my-flag --name "My Flag" --active true
posthog-cli feature-flag delete --id 123
posthog-cli dashboard get-all
posthog-cli experiment launch --id 5
```

- **Per-category grouping** (O4): `posthog-cli <category> <verb>`. Categories and verbs are derived
  in the generator from the human category name + tool name (e.g. "Feature flags" + `create-feature-flag`
  → `feature-flag create`), with collision-safe fallback to the raw tool name.
- **Hybrid flags + `--json`**: scalar params become real `--flags` (typed `--active <BOOLEAN>`);
  nested/complex params (objects, arrays) go through `--json`. Explicit flags override `--json` keys.
- **Native `--help` at every level** — the discovery story, for free from clap:
  - `posthog-cli --help` lists built-in commands **and** generated categories
  - `posthog-cli feature-flag --help` lists the verbs
  - `posthog-cli feature-flag create --help` lists the flags + types
- **`--dry-run`** prints the resolved request (used in every demo above).
- Built-in commands (`login`, `sourcemap`, `exp`, …) are untouched and coexist; a category that
  would shadow a built-in name is skipped.

## How it's wired

- Generator (`generate-cli-manifest.ts`): derives `category` (slug) + `verb` per tool, and marks
  scalar params `flag_eligible` using OpenAPI/body types. Collisions per category fall back to the
  raw tool name so two tools never map to the same `<category> <verb>`.
- Rust (`cli/src/agent/command.rs`): `augment_with_categories()` builds the clap command tree from
  the manifest at startup and merges it into the top-level CLI (`commands.rs`); `dispatch_category()`
  assembles params from flags + `--json` and runs the same `build_request` + execute path. The raw
  `exp agent` interface remains for scripting.

All 17 conformance/interpreter tests still pass; the request-building path is unchanged (the new code
only assembles params before handing off to the verified interpreter).

## Remaining Phase 2 polish (not yet done)

- **Per-tool descriptions in `--help`** — currently shows `METHOD path`; the manifest could carry the
  tool description (already resolved in the pipeline) for richer help.
- **Machine-readable discovery** — `list --json` / `schema <category> <verb> --json` for token-efficient
  agent discovery (native `--help` is human-formatted).
- **Path params as positionals** — `feature-flag delete 123` instead of `--id 123`, if preferred.
- **`skill list` / `skill install`** (O2).
- **Steering injection** — the canonical user-facing steering block is now authored at
  `cli/src/agent/steering.md` (delimited by `posthog:cli` markers). Still TODO: a `posthog-cli`
  setup/init command that writes/refreshes that block in the end user's `AGENTS.md` (Phase 4).
- Naming edge cases for a few categories (e.g. query wrappers land under `query-wrapper`); revisit the
  slug rule if any read poorly.
