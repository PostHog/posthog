# PostHog CLI 2.0

Experimental PostHog CLI backed by generated MCP tool definitions.

The package is intended to install a `ph` binary, so users can run commands like:

```bash
ph auth login
ph actions get-all
ph dashboards get-all
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
pnpm dev actions --help
pnpm dev actions get-all
```

`dev` does not compile TypeScript and does not regenerate command definitions.

### `pnpm generate:commands`

Regenerates CLI command definitions:

```bash
pnpm generate:commands
```

This reads MCP tool definitions from `../services/mcp/schema/tool-definitions-all.json` and writes `src/generated/commands.ts`.

Run this when MCP tool definitions change or when `src/generated/commands.ts` is missing/out of date.

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
pnpm start actions --help
```

`start` does not rebuild. If `dist/` is missing or stale, run `pnpm build` first.

### `pnpm pack`

`prepack` runs `pnpm build` automatically so packed/published artifacts include the compiled CLI output.

## Script responsibilities

| Script | Purpose | Regenerates commands? | Compiles TypeScript? | Runs built `ph` path? |
| --- | --- | --- | --- | --- |
| `pnpm dev <command>` | Fast local development against `src/index.ts` | No | No | No |
| `pnpm generate:commands` | Refresh `src/generated/commands.ts` from MCP schema | Yes | No | No |
| `pnpm build` | Prepare compiled output in `dist/` | Yes | Yes | No |
| `pnpm link:global` | Build and globally link the `ph` binary | Yes, via `build` | Yes, via `build` | Yes |
| `pnpm start <command>` | Run production-like built CLI | No | No | Yes |

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

Help commands and bare command groups, such as `ph auth` or `ph actions`, do not require login and show their available subcommands.

## Adding or changing commands

Most CLI command groups are generated from MCP tool definitions, not handwritten.

1. Update the relevant MCP tool definition/source.
2. Run `pnpm generate:commands` or `pnpm build`.
3. Inspect `src/generated/commands.ts`.
4. Test source mode with `pnpm dev <group> --help`.
5. Test the installed-user path with `pnpm build && node ./bin/ph.js <group> --help`.

Do not manually edit `src/generated/commands.ts` unless you are debugging generated output; regenerate it instead.
