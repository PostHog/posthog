# PostHog CLI 2.0

PostHog CLI with human-readable command names backed by enhanced MCP tool mappings.

The package provides a `ph` binary with semantic command names that reflect actual functionality:

```bash
ph auth login
ph feature-flags status --id 660245
ph cohorts list
ph cohorts add-persons --id 123
ph insights list
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
```

`dev` does not compile TypeScript and does not regenerate command definitions.

### `pnpm generate:commands`

Regenerates CLI command definitions:

```bash
pnpm generate:commands
```

This reads MCP tool definitions from `../services/mcp/schema/tool-definitions-all.json`, generates enhanced command mappings in `schema/command-mappings-enhanced.json`, and writes `src/generated/commands.ts` with human-readable command names.

The enhanced mappings system:

- Maps 312+ MCP tools to semantic command names
- Extracts real API endpoints from MCP tool implementations
- Uses simple template placeholders (`{project_id}`, `{id}`)
- Groups commands logically (feature-flags, cohorts, insights, etc.)

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

## Available Commands

The CLI provides 40+ command groups with 312+ subcommands:

**Core Resources:**

- `ph feature-flags` - Feature flag management (status, list, create, etc.)
- `ph cohorts` - Cohort operations (list, add-persons, remove-persons, etc.)
- `ph insights` - Insight and query management
- `ph dashboards` - Dashboard operations
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

## Adding or changing commands

CLI command groups are generated from MCP tool definitions using an enhanced mapping system.

### Command Generation Process

1. **MCP Tool Definitions** - Source definitions from `../services/mcp/schema/tool-definitions-all.json`
2. **Enhanced Mapping Generator** - `scripts/generate-command-mappings-v2.ts` creates semantic command mappings
3. **Command Generator** - `scripts/generate-commands.ts` creates the final CLI structure

### Making Changes

**For new commands:**

1. Add/modify MCP tool definitions in the services/mcp directory
2. Run `pnpm generate:commands` to regenerate mappings and commands
3. Test with `pnpm dev <group> <command> --help`

**For command naming improvements:**

1. Update patterns in `scripts/generate-command-mappings-v2.ts`
2. Add specific mappings for tools that don't follow general patterns
3. Regenerate with `pnpm generate:commands`

**For endpoint/API issues:**

1. Check enhanced mappings in `schema/command-mappings-enhanced.json`
2. Verify endpoint extraction in `extractEndpointFromGeneratedTool()`
3. Add specific mappings if needed

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
