---
name: dynamic-workflows
description: How to write JavaScript workflow scripts for the `workflow` tool - fanning work out across many isolated subagents with agent(), parallel(), and pipeline(), then synthesizing one result. Use when a task decomposes into several independent investigations or changes (codebase audits, many-file analysis, wide research, multi-perspective review, applying the same edit across many independent files).
---

# Dynamic Workflows

The `workflow` tool executes a JavaScript orchestration script you write. The script
holds the loop, branching, and intermediate results; each `agent()` call runs one
isolated subagent in its own pi process; only the script's return value comes back
into your context. This is how you audit 20 files, research 8 topics, or apply the
same change across 20 independent files without burning your own context window on
the intermediate output.

## When to use it

- The work decomposes into **several independent investigations or changes** whose
  intermediate outputs you don't need verbatim - only a synthesis (or a report of
  what changed).
- Examples: audit every route/module for a property, summarize each package of a
  monorepo, verify a list of findings adversarially, research N alternatives, rename
  an API across every file that references it.

Do **not** use it for: a single question or a single edit (use `subagent` or just do
it directly), one or two parallel tasks (use `subagent` parallel mode), or work
needing your full conversation context.

## Script shape

Prefer the **strict declared-plan contract** below. Strict mode turns on only when
`meta.phases` is a literal object the runtime can read without executing code;
older/dynamic scripts keep their legacy behavior. Do not set token budgets: choose
only the appropriate persona/model tier and let the host account actual usage.

```javascript
export const meta = {
  name: 'audit_routes',
  goal: 'Produce a decision-ready router audit',
  inputs: ['repository'],
  phases: [
    { title: 'Scan', goal: 'Map routers', inputs: ['repository'], produces: ['router inventory'] },
    { title: 'Audit', goal: 'Check the inventory', inputs: ['router inventory'], produces: ['router audits'] },
    { title: 'Synthesize', goal: 'Deliver the verdict', inputs: ['router audits'], produces: ['audit verdict'] },
  ],
  synthesis: { phase: 'Synthesize', inputs: ['router audits'], produces: ['audit verdict'] },
}

phase('Scan')

const inventory = await agent(
  'List every *.router.ts file under packages/host-router/src/routers. Reply with only JSON.',
  {
    label: 'route inventory',
    objective: 'Produce the complete router inventory for the audit.',
    inputs: ['repository'],
    produces: 'router inventory',
    schema: { type: 'object', required: ['files'], properties: { files: { type: 'array', items: { type: 'string' } } } },
  },
)
if (!inventory) return { ok: false, error: 'inventory failed' }

phase('Audit')
const audits = await agent(
  'Audit the router inventory against the one-line-forward rule. Return every violation as JSON.',
  { label: 'router audit', objective: 'Audit all discovered routers for inline logic.', inputs: ['router inventory'], produces: 'router audits', schema: { type: 'object', required: ['violations'] } },
)

phase('Synthesize')
const verdict = await agent(
  'Summarize the supplied router audits into {ok, violations: [...]}. Reply with only JSON.',
  { label: 'final verdict', agent: 'Plan', objective: 'Create the final decision-ready audit report.', inputs: ['router audits'], produces: 'audit verdict', schema: { type: 'object', required: ['ok', 'violations'] } },
)
return verdict
```

In strict mode, activate declared phases exactly in order; agent inputs are artifact-name arrays (not inline records), every declared phase output must be published exactly once (an agent automatically publishes its declared `produces`, or use `publish(name, value)` for aggregates), and the final `synthesis` phase must publish its named final artifact. Give every phase a goal, every agent a unique label and objective, and all real handoffs named inputs/outputs.

Rules: plain JavaScript (no TypeScript, no `import`/`require`); the leading
`export const meta = { name, description }` is optional but conventional; the script
must call `agent()` at least once; the return value must be JSON-serializable (a
common mistake is returning an unawaited `agent()` promise).

## API

| Global | Behavior |
|--------|----------|
| `agent(prompt, opts)` | Runs one subagent; resolves to its final text, or the parsed+shape-checked object when `opts.schema` is set, or `null` on failure. Opts: `label` (short, unique - drives the live display), `objective` (responsibility), `inputs` (artifact-name strings or a record of named string values), `produces` (one artifact name), `agent` (`'Explore'` default, `'Plan'`, or `'General'`), `schema` (plain JSON Schema), `cwd`, `model` (tier keyword, see below). |
| `parallel(thunks)` | `await parallel(items.map(i => () => agent(...)))` - functions, **not** promises. Results in input order; failed branches are `null`. |
| `pipeline(items, ...stages)` | Fans items through sequential stages (map → verify → summarize). Items run concurrently; each item's stages run in order; each stage receives `(previousValue, originalItem, index)`. A failed stage nulls that item's slot. |
| `phase(title, meta?)` | Marks a new stage of work for the live progress display. Prefer `phase('Audit', { goal: '...', inputs: ['inventory'], produces: ['findings'] })` so the upcoming plan and dependencies are visible before it runs. `goal`, `inputs`, and `produces` are optional; dynamic/conditional phases remain supported. |
| `log(message)` | Appends a workflow-level log line (shown in the expanded view). |
| `parseJson(text)` | Extracts JSON from an agent's text reply, tolerating fences and surrounding prose. Prefer `schema` on `agent()` instead. |
| `args` | The JSON value passed in the tool call's `args` parameter. |
| `cwd` | The workflow's working directory (string). |

Limits: 8 agents run concurrently, 256 per workflow. `require`, `fs`, `fetch`, and
timers are unavailable inside the script - all real work happens inside subagents.

## Which agent

| Agent | Capability | Model (default) | Use for |
|-------|------------|------------------|---------|
| `Explore` (default) | Read-only | Fast/cheap | Recon, per-item checks, broad search |
| `Plan` | Read-only | Inherits your model | Judgment-heavy planning or synthesis |
| `General` | **Read-write** | Inherits your model | The actual edits an investigation identified, or any fan-out that needs real changes |

Only `General` edits files. Reach for it when a change is mechanical/independent
enough to parallelize (e.g. the same fix across many files) rather than applying every
edit yourself after the workflow returns.

## Model override

`agent()`'s `model` option picks a different model than the persona's own default for
just that call, using a **tier keyword**, not a guessed exact model id (the available
model list changes over time, so a literal id can silently be wrong):

- `'strong'` - the best available model. Use for a genuinely hard `General` edit or a
  judgment call worth spending more on.
- `'medium'` - a solid mid-tier model.
- `'cheap'` - fast and cheap. Use to bump a `Plan`/`General` call down for something
  simple, or to run more `Explore`-style recon than the default budget would allow.

Omit `model` entirely to use the persona's own default (most calls should).
```javascript
await agent('Investigate whether this auth check has a bypass.', { agent: 'Plan', model: 'strong', label: 'auth bypass check' })
```

## Failure semantics

A failed `agent()` / `parallel()` branch / `pipeline()` item becomes `null` plus a log
line; the rest of the workflow continues. **Always check for nulls before
synthesizing** - `audits.filter(Boolean)` or an explicit guard. Only aborts and script
bugs (unknown agent name, bad arguments, exceeding limits) fail the whole workflow.

## Writing good workflows

- Subagents share no context with you or each other: every prompt must carry its own
  file paths, constraints, and any prior findings it depends on. Add `objective`,
  `inputs`, and `produces` to each agent call: they add a concise child context block
  and let the live workflow show responsibility and downstream artifact use.
- Use `schema` whenever an agent's output feeds a later stage; use free text only for
  the final human-readable synthesis. Define a schema once in a `const` and reuse it
  across parallel agents instead of repeating large nested object literals.
- End with a synthesis step and return a **compact** value (verdict + key findings),
  not a dump of every intermediate output - the return value is all you get back.
- Default to `Explore` for recon and per-item checks, `Plan` for judgment-heavy
  synthesis, and `General` only for the calls that actually need to write files.
