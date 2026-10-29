# hog

`hog` is the PostHog command line, version 1. Read [README.md](README.md) for what it does and how to run it.

## Layout

| Path                  | Holds                                                                                                                                                                                     |
| --------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/commands/`       | One file per command. `index.ts` is the tree of every command; `legacy.ts` holds the ones posthog-cli still owns                                                                          |
| `src/core/`           | The shared parts every command uses: command definitions, context and global options, output, agent detection, errors, runtime, the manifest                                              |
| `src/posthog/`        | The PostHog API client and credentials                                                                                                                                                    |
| `src/error-tracking/` | Symbol upload: discovery, artifact types under `kinds/`, the container and content hash, releases, git, the upload protocol, and `run.ts`, the inject and upload steps the commands share |
| `src/endpoints/`      | The endpoint YAML files, how they compare with PostHog, and the push and pull plans                                                                                                       |
| `test/parity/`        | Goldens recorded from posthog-cli and the tests that hold hog to them. Read its README before changing anything that reaches an upload                                                    |
| `src/cli.ts`          | Turns the command tree into a commander program, runs it, and maps errors to exit codes                                                                                                   |
| `src/testing.ts`      | `runHog` and a fake runtime, so tests run the real CLI without a process or a network                                                                                                     |

Import from another folder with `@/`, which `tsconfig.json` maps to `src/`, as in `import { defineCommand } from '@/core/command'`. Use `./` only inside the same folder.

## Add a command

1. Write `src/commands/<group>/<name>.ts` with `defineCommand`. Put it in a `defineGroup` when it has siblings.
2. Add it to the tree in `src/commands/index.ts`, and remove its `defineLegacy` entry from `src/commands/legacy.ts` if posthog-cli has one. A legacy entry can sit inside a group, so a group can be half ported.
3. Add cases to `src/commands/<group>/<group>.test.ts` with `runHog`.

```ts
export default defineCommand({
  description: 'List the feature flags in your project',
  args: { search: { description: 'Only show flags whose key contains this text', optional: true } },
  options: { active: { type: 'boolean', description: 'Only show active flags' } },
  scopes: ['feature_flag:read'],
  examples: ['hog flags list checkout'],

  async run({ args, options, ctx }) {
    const api = await ctx.posthog()
    const flags = await api.get<{ results: Flag[] }>(`feature_flags/?search=${encodeURIComponent(args.search ?? '')}`)
    return options.active ? flags.results.filter((flag) => flag.active) : flags.results
  },
  human({ result, out }) {
    out.table(
      ['key', 'active'],
      result.map((flag) => [flag.key, flag.active])
    )
  },
  agent({ result, out }) {
    out.jsonLines(result)
  },
})
```

## Rules

- `run` returns data and never prints. `human` decides what a person at a terminal sees, and `agent` decides what agents, pipes and `-o json` see. Without them, people get indented JSON and agents get one line of JSON.
- Agent output is JSON only, on stdout, with no color and no prose. Prefer `out.jsonLines` for lists, so an agent can stream them.
- `out.table` colors each column by kind (number, date, boolean, JSON) and fits the terminal width. Pass a `kind` when the API declares column types, as `hog query run` does with ClickHouse types. Otherwise the kind comes from the values.
- A failure throws a `HogError` with a stable `code` and a `hint` that names the next step. `cli.ts` prints it as text or as JSON on stderr. Do not catch errors to print them yourself.
- Ask questions only through `ctx.prompts`. It is undefined for agents, pipes and `-o json`, so a command that needs an answer must take it as an option there, or fail with a hint that names the option. Never block an agent on a person: split the work into a call that returns at once and a call that finishes it, like `hog auth login` and `hog auth login --wait`.
- `exitCode` is for results that are not failures but that a script must branch on, like `hog query check` finding errors.
- `--raw` is global: it prints the result of `run` as JSON and skips both views. Do not add per-command `--raw` or `--debug` flags; return enough data from `run` instead.
- An argument with `stdin: true` reads stdin when the caller passes `-`, and fails when it is empty. `hog commands` tells agents which arguments accept it.
- Commands reach the outside world only through `ctx` (`ctx.posthog()`, `ctx.runtime`), so tests can fake it. Do not read `process` or call `fetch` directly.
- Import heavy dependencies inside `run` with `await import()`. Every command module loads on every call, so a top-level import of a large library slows down all commands.
- Declare `scopes`. `hog commands` lists them for agents, and a 403 names them in its hint.
- `hog error-tracking` must upload the same bytes, content hashes and requests as posthog-cli, or re-uploads fail with `content_hash_mismatch`. A change to anything that reaches an upload keeps `test/parity/` green, and a new artifact type or flag adds parity scenarios recorded from posthog-cli.
- Code under `src/error-tracking/` reads build output with `node:fs` directly, because it walks real folders. Its tests use temporary folders instead of `ctx.runtime` files.
- Every string a person reads follows `/writing-user-facing-copy`: sentence case, no em dashes.
