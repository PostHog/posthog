# PostHog CLI 2.0

PostHog CLI with human-readable command names backed by enhanced MCP tool mappings.

The package provides a `ph` binary with semantic command names that reflect actual functionality:

```bash
ph auth login
ph feature-flags list
ph feature-flags view --id 660245
ph feature-flags status --id 660245
ph cohorts list
ph cohorts view --id 123
ph insights list
ph insights view --id ueWYzLgD     # plots a trends insight as an ASCII chart
ph dashboards list
```

## Setup

```bash
pnpm install
```

## Use it as a CLI

Build the package first:

```bash
pnpm build
```

Then run the binary wrapper directly:

```bash
node ./bin/ph.js auth --help
node ./bin/ph.js auth login
```

Or link it globally while developing:

```bash
pnpm run link:global
ph auth --help
ph auth login
```

`pnpm run link:global` builds the CLI first, then runs `pnpm link --global`.

If pnpm reports `ERR_PNPM_NO_GLOBAL_BIN_DIR`, configure a global bin directory that is already on your `PATH`. On this machine, `~/.local/bin` is on `PATH`, so this fixes it:

```bash
mkdir -p ~/.local/bin
pnpm config set global-bin-dir ~/.local/bin
pnpm run link:global
```

Alternatively, run `pnpm setup` and restart your shell.

The `bin` entry in `package.json` maps `ph` to `./bin/ph.js`. The wrapper runs the compiled CLI from `dist/index.js`, which is what installed users exercise.

## Common scripts

### `pnpm dev <command>`

Runs `src/index.ts` directly with `tsx`.

Use this for the fastest local development loop when editing CLI source code:

```bash
pnpm dev auth --help
pnpm dev auth login
pnpm dev feature-flags --help
pnpm dev cohorts list
pnpm dev insights view --id ueWYzLgD
```

`dev` does not compile TypeScript and does not regenerate command definitions.

### `pnpm generate:commands`

Regenerates CLI command definitions:

```bash
pnpm generate:commands
```

This reads MCP tool definitions from `../services/mcp/schema/tool-definitions-all.json`, generates enhanced command mappings in `schema/command-mappings-enhanced.json`, and writes `src/generated/commands.ts` with human-readable command names.

The enhanced mappings system:

- Maps 365 MCP tools across 44 command groups
- Derives subcommand names from each tool's structure: strips the resource alias prefix and the CRUD verb suffix; what remains becomes the modifier (e.g. `feature-flags-evaluation-reasons-retrieve` → `evaluation-reasons`)
- Falls back to gh-style verbs when no modifier is left: `get`/`retrieve` → `view`, `get-all`/`list` → `list`, `partial-update`/`update` → `update`, `destroy`/`delete` → `delete`
- Groups by source file (`services/mcp/src/tools/generated/<file>.ts` → `FILE_GROUPS` in `scripts/generate-command-mappings.ts`); heterogeneous files like `core.ts` and `platform_features.ts` use per-tool-prefix routing
- Treats name collisions as a hard error — the script fails with both tool names and points at the `EXPLICIT_NAMES` override map (no silent `-1`/`-2` suffixes)

Run this when MCP tool definitions change or when generated files are missing/out of date.

### `pnpm build`

Prepares the package for CLI usage:

```bash
pnpm build
```

`build` runs command generation first, then compiles TypeScript into `dist/`.

Run this before using `node ./bin/ph.js`, `pnpm start`, global linking, packing, or publishing.

### `pnpm start <command>`

Runs the built CLI through the package binary wrapper:

```bash
pnpm start auth --help
pnpm start feature-flags --help
```

`start` does not rebuild. If `dist/` is missing or stale, run `pnpm build` first.

### `pnpm pack`

`prepack` runs `pnpm build` automatically so packed/published artifacts include the compiled CLI output.

## Script responsibilities

| Script                   | Purpose                                             | Regenerates commands? | Compiles TypeScript? | Runs built `ph` path? |
| ------------------------ | --------------------------------------------------- | --------------------- | -------------------- | --------------------- |
| `pnpm dev <command>`     | Fast local development against `src/index.ts`       | No                    | No                   | No                    |
| `pnpm generate:commands` | Refresh `src/generated/commands.ts` from MCP schema | Yes                   | No                   | No                    |
| `pnpm build`             | Prepare compiled output in `dist/`                  | Yes                   | Yes                  | No                    |
| `pnpm link:global`       | Build and globally link the `ph` binary             | Yes, via `build`      | Yes, via `build`     | Yes                   |
| `pnpm start <command>`   | Run production-like built CLI                       | No                    | No                   | Yes                   |

## Authentication

Most commands require authentication:

```bash
ph auth login
```

If a command fails with `API key missing required scope`, run `ph auth login` again after updating scopes. Existing OAuth tokens do not automatically gain newly requested scopes.

For local testing with extra scopes, override the defaults:

```bash
POSTHOG_CLI_OAUTH_SCOPES="openid profile email project:read organization:read user:read dashboard:read insight:read feature_flag:read feature_flag:write experiment:read" ph auth login
```

Check current auth state:

```bash
ph auth status
```

Clear stored credentials:

```bash
ph auth logout
```

Help commands and bare command groups, such as `ph auth` or `ph feature-flags`, do not require login and show their available subcommands.

To run a command against a different project without changing the stored project, pass `--project-id`.
The stored access token or API key must already have access to that project, otherwise the API request will fail.

```bash
ph --project-id 12345 feature-flags list
ph insights list --project-id 12345
```

Commands print a human-friendly summary by default. Pass `--json` to get the raw API response — useful for scripting:

```bash
ph insights view --id ueWYzLgD --json | jq .result
```

## Available Commands

The CLI provides 44 command groups across 365 subcommands:

**Core Resources:**

- `ph feature-flags` - Feature flag management (list, view, status, create, etc.)
- `ph cohorts` - Cohort operations (list, view, create, update, add-persons, remove-persons)
- `ph insights` - Insight management; `ph insights view --id <short_id>` plots trends as ASCII charts and renders funnels as conversion tables
- `ph dashboards` - Dashboard operations; `ph dashboards run --id <id>` runs every insight on a dashboard
- `ph experiments` - A/B test management
- `ph persons` - Person and user data

**Analytics & Tracking:**

- `ph events` - Event data and definitions
- `ph actions` - Action tracking configuration
- `ph session-recordings` - Session replay management
- `ph web-analytics` - Web analytics features

**Platform Features:**

- `ph organizations` - Organization management
- `ph projects` - Project configuration
- `ph users` - User management
- `ph roles` - Access control

Run `ph --help` to see all available command groups, or `ph <group> --help` for subcommands.
Subcommands use the generated human-readable names shown in help output, not raw MCP tool names; for example use `ph feature-flags list`, not `ph flags feature-flag-get-all`.

## Adding or changing commands

CLI command groups are generated from MCP tool definitions using an enhanced mapping system.

### Command Generation Process

1. **MCP Tool Definitions** - Source definitions from `../services/mcp/schema/tool-definitions-all.json`
2. **Enhanced Mapping Generator** - `scripts/generate-command-mappings.ts` produces `schema/command-mappings-enhanced.json` from those definitions plus the generated tool sources in `../services/mcp/src/tools/generated/`
3. **Command Generator** - `scripts/generate-commands.ts` consumes the enhanced mappings and writes `src/generated/commands.ts`

### Making Changes

**For new commands:**

1. Add/modify MCP tool definitions in the services/mcp directory
2. Run `pnpm generate:commands` to regenerate mappings and commands
3. Test with `pnpm dev <group> <command> --help`

**For naming or grouping changes:**

1. Tool naming follows the alias-strip + verb-strip algorithm in `scripts/generate-command-mappings.ts`. To force a specific name, add an entry to the `EXPLICIT_NAMES` map in that file
2. To change which group a tool lands in, update `FILE_GROUPS` (per source file) or `NON_GENERATED_GROUPS` (for hand-written tools that aren't in `generated/*.ts`)
3. Regenerate with `pnpm generate:commands` — if two tools resolve to the same subcommand name, the script fails loudly and tells you which `EXPLICIT_NAMES` entry to add

**For endpoint/API issues:**

1. Check enhanced mappings in `schema/command-mappings-enhanced.json`
2. Endpoints are parsed from the generated tool sources by `parseGeneratedTools()` in `scripts/generate-command-mappings.ts`

### Testing Changes

```bash
# Test development version
pnpm dev feature-flags status --id 123

# Test built version
pnpm build && node ./bin/ph.js feature-flags status --id 123

# Check command structure
pnpm dev feature-flags --help
```

Do not manually edit generated files (`src/generated/commands.ts`, `schema/command-mappings-enhanced.json`) - regenerate them instead.
