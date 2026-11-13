# hog

`hog` is the PostHog command line. Read [README.md](README.md) for what it does and how to run it.

## Layout

| Path                  | Holds                                                                                                                                                                                     |
| --------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/commands/`       | One file per command. `index.ts` is the tree of every command; `legacy.ts` holds the ones posthog-cli still owns                                                                          |
| `src/core/`           | The shared parts every command uses: command definitions, context and global options, output, agent detection, errors, runtime, the manifest                                              |
| `src/posthog/`        | The PostHog API client, the pagination helpers every list uses, and credentials                                                                                                           |
| `src/ci/`             | CI setup. `providers/registry.ts` lists the providers whose OIDC tokens hog exchanges, and each provider has its own folder                                                               |
| `src/error-tracking/` | Symbol upload: discovery, artifact types under `kinds/`, the container and content hash, releases, git, the upload protocol, and `run.ts`, the inject and upload steps the commands share |
| `src/setup/`          | `hog setup`: the steps, the state file each folder keeps in `~/.posthog/setup/`, the AGENTS.md note and the product table                                                                 |
| `src/endpoints/`      | The endpoint YAML files, how they compare with PostHog, and the push and pull plans                                                                                                       |
| `src/updates/`        | The release manifest format, the release targets and version parsing, which `release/` uses                                                                                               |
| `release/`            | The release scripts the `Release hog` workflow runs (compile, package), `install.sh`, `install.ps1` and the npm launcher. README.md, "Releases", has the flow                             |
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
  options: {
    limit: {
      type: 'string',
      placeholder: 'count',
      parse: parseLimit,
      description: 'How many flags to show, up to 1000',
    },
    offset: { type: 'string', placeholder: 'count', parse: parseOffset, description: 'How many flags to skip' },
  },
  scopes: ['feature_flag:read'],
  examples: ['hog flags list checkout'],

  async run({ args, options, ctx }) {
    const query = new URLSearchParams({
      search: args.search ?? '',
      limit: String(options.limit ?? 100),
      offset: String(options.offset ?? 0),
    })
    const page = await getPage(await ctx.posthog(), `feature_flags/?${query}`, Flag)
    return { flags: page.results, nextOffset: nextOffset(page) }
  },
  human({ result, out }) {
    out.table(
      ['key', 'active'],
      result.flags.map((flag) => [flag.key, flag.active])
    )
    if (result.nextOffset !== null) {
      out.notes({
        notes: [`Run ${out.style(`hog flags list --offset ${result.nextOffset}`, 'bold')} for the next page.`],
      })
    }
  },
  agent({ result, out }) {
    out.json(result)
  },
})
```

## Rules

- `run` returns data and never prints. `human` decides what a person at a terminal sees, and `agent` decides what agents, pipes and `-o json` see. Without them, people get indented JSON and agents get one line of JSON.
- Human output reads result, then side effects, then notes. A command that changes something prints through `out.report`: its first line says whether the command worked, the lines under it say what changed, and warnings, tips and next steps come last. A command that prints data prints the data first, then passes page hints, tips and warnings to `out.notes`.
- Agent output is JSON only, on stdout, with no color and no prose. Prefer `out.jsonLines` for rows a command reads in one go, like query results, so an agent can stream them. A paged list prints one JSON object, so it can carry the next offset.
- A command never reads a whole PostHog list. A list command reads one page per run with `getPage` from `src/posthog/pagination.ts`. It takes `--limit` and the option that picks a page in that endpoint's DRF paginator, such as `--offset`. Its human output names the command for the next page, and its agent output has the next offset as a field. A command that needs particular items from a list uses `findNamed`, which stops when it has them. Only a command whose purpose is the whole list, like `hog endpoints pull --all`, uses `readAll`. Both stop at `MAX_PAGES`.
- `out.table` colors each column by kind (number, date, boolean, JSON) and fits the terminal width. Pass a `kind` when the API declares column types, as `hog query run` does with ClickHouse types. Otherwise the kind comes from the values.
- A failure throws a `HogError` with a stable `code` and a `hint` that names the next step. `cli.ts` prints it as text or as JSON on stderr. Do not catch errors to print them yourself.
- Ask questions only through `ctx.prompts`. It is undefined for agents, pipes and `-o json`, so a command that needs an answer must take it as an option there, or fail with a hint that names the option. Never block an agent on a person: split the work into a call that returns at once and a call that finishes it, like `hog auth login` and `hog auth login --wait`. A command that waits for a person to approve something in a browser uses `runApproval` and `resumeApproval` from `src/core/approval.ts`, so every such command starts, waits and resumes the same way.
- `exitCode` is for results that are not failures but that a script must branch on, like `hog query check` finding errors.
- `--raw` is global: it prints the result of `run` as JSON and skips both views. A command whose result is a trimmed view of a PostHog answer, like `hog query run`, keeps the whole answer in it and returns that from `raw`. Do not add per-command `--raw` or `--debug` flags; return enough data from `run` instead.
- An argument with `stdin: true` reads stdin when the caller passes `-`, and fails when it is empty. `hog commands` tells agents which arguments accept it.
- Data that enters hog, such as flags, env vars, files, keychain items and answers from PostHog, is parsed into a typed value at the boundary with a zod schema. It is not checked and then passed on as a plain string. A branded value, such as a `Host`, a `ProjectId` or a token kind, comes only from its factory, such as `parseHost` or `parseProjectId`. Semgrep blocks `JSON.parse` outside `src/core/json.ts` and a cast to a brand outside the module that defines it (`.semgrep/rules/devex/hog-typed-boundaries.yaml`).
- Commands reach the outside world only through `ctx` (`ctx.posthog()`, `ctx.runtime`), so tests can fake it. Do not read `process` or call `fetch` directly.
- Import heavy dependencies inside `run` with `await import()`. Every command module loads on every call, so a top-level import of a large library slows down all commands.
- Declare `scopes`. `hog commands` lists them for agents, and a 403 names them in its hint.
- `hog error-tracking` must upload the same bytes, content hashes and requests as posthog-cli, or re-uploads fail with `content_hash_mismatch`. A change to anything that reaches an upload keeps `test/parity/` green, and a new artifact type or flag adds parity scenarios recorded from posthog-cli.
- Code under `src/error-tracking/` reads build output with `node:fs` directly, because it walks real folders. Its tests use temporary folders instead of `ctx.runtime` files.
- Every string a person reads follows `/writing-user-facing-copy`: sentence case, no em dashes.
