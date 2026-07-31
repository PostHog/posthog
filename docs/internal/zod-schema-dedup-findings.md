# Deduplicating generated Zod schemas — measurements

Investigation into whether the OpenAPI → Zod pipeline can stop inlining every `$ref`, and whether
that would shrink the JSON Schema each MCP tool advertises.

Short version: **neither available lever is a global win.** Both help a handful of large schemas and
cost a little on everything else. Numbers below so the next person doesn't have to re-derive them.

## What prompted it

`services/mcp/tests/unit/__snapshots__/tool-schemas/project-settings-update.json` carries the same
subtrees over and over — 28% of that one tool's schema is byte-identical repetition, mostly a
34-value operator enum copied 30 times and a 152-value currency enum copied 3 times.

A comment in `frontend/bin/generate-openapi-types.mjs` explains why:

> Orval's Zod client fully inlines every `$ref` instead of using `z.lazy()`

That is true of our configuration, but not of Orval. Since 8.14 there is
`override.zod.generateReusableSchemas`, and one generator in this repo already sets it
(`products/dashboards/frontend/bin/generate-widget-config-zod.mjs`). The comment is worth
rewording.

## Lever 1 — `generateReusableSchemas` in the shared generator

One line in the Zod Orval config. Emits shared named schemas into an `api.zod.schemas.ts` sibling
instead of inlining each `$ref`.

Regenerating every `api.zod.ts` with it on, comparing against master:

|               | total generated Zod source |
| ------------- | -------------------------- |
| master        | 3,305,299 B                |
| with the flag | 3,454,259 B (**+4.5%**)    |

53 of 66 files get bigger, 12 get smaller. The split is by size:

| file                                     | before                                | after                     |
| ---------------------------------------- | ------------------------------------- | ------------------------- |
| `frontend/src/generated/core/api.zod.ts` | 837,122                               | 190,035 (**−77%**)        |
| next four largest                        | 288,575 / 173,148 / 164,224 / 114,340 | −72% / −58% / −39% / −75% |
| a typical small product file             | 3,554                                 | 66,843 (**+1781%**)       |

The flag makes Orval emit _every_ component schema as a named export, so a product file that
previously inlined the three schemas it needed now carries the whole component set. Worth enabling
per output directory where the file is large; not worth flipping globally.

Note this lever only changes generated **source** size. It does not touch what MCP clients receive.

## Lever 2 — `reused: 'ref'` when serializing tool schemas

`services/mcp/src/tools/exec.ts` calls `z.toJSONSchema(tool.schema, { io: 'input' })`. Zod v4
defaults `reused: 'inline'`, so a schema used twice is expanded twice. Passing `reused: 'ref'`
extracts repeats into `$defs`.

Measured across all 574 tools:

| strategy                     | total advertised schema  | tools over the 16,384 client limit |
| ---------------------------- | ------------------------ | ---------------------------------- |
| `inline` (today)             | 2,024,585 B              | 29                                 |
| `ref` everywhere             | 1,793,885 B (−11.4%)     | **36**                             |
| smaller of the two, per tool | 1,581,974 B (**−21.9%**) | 29                                 |

`ref` everywhere is a trap: it shrinks the query tools a lot (`query-retention` 73,654 → 19,951,
−73%) but costs 51 B on each of the 358 tools with nothing to share, and pushes seven tools over
the client limit that were under it:

```text
action-create                      14,519 -> 22,206
action-update                      14,625 -> 22,312
batch-export-create                12,418 -> 17,186
cdp-functions-invocations-create   14,638 -> 17,559
dashboard-widgets-batch-update     14,887 -> 17,199
workflows-create                   14,237 -> 16,944
batch-export-update                12,177 -> 16,565
```

Picking the smaller serialization per tool is strictly better than today and never worse for any
individual tool, since it is a per-tool minimum. Only 19 of 574 tools would use `ref`.

**Unverified, and the reason this isn't a PR yet:** whether the MCP clients we care about resolve
`$defs`/`$ref` inside a tool's `inputSchema`. If any client expects a self-contained schema, the 19
tools that switch would break there. That needs checking against real clients before shipping,
and it is the whole risk of lever 2.

## What neither lever fixes

Tool schema size is dominated by things unrelated to `$ref` duplication. On master,
`project-settings-update` is 38,611 B, of which:

| field                      | bytes  | share |
| -------------------------- | ------ | ----- |
| `timezone`                 | 22,445 | 58%   |
| `revenue_analytics_config` | 3,336  | 8.6%  |
| `base_currency`            | 3,233  | 8.4%  |
| the other 65 fields        | 9,597  | 25%   |

`timezone` is a single `string` field whose generated description lists all ~400 IANA zones twice
each (`* \`Africa/Abidjan\` - Africa/Abidjan`). Truncating that one description frees 22 KB and
would put the tool under the client limit on its own — more than either lever here yields.

## Suggested order

1. Truncate the `timezone` description. Largest win, smallest change, no compatibility question.
2. Add a size assertion for tool schemas. Today only the `exec` tool has one
   (`services/mcp/tests/unit/instructions-formatter-snapshot.test.ts`); nothing guards the other 573.
3. Enable `generateReusableSchemas` for the few output directories where the file is large.
4. Only then look at per-tool `reused: 'ref'`, and only after confirming client `$ref` support.

## Reproducing

Lever 1: add `generateReusableSchemas: true` to the `override.zod` block in
`frontend/bin/generate-openapi-types.mjs` (the change on this branch) and run `hogli build:openapi`.

Lever 2: the per-tool numbers come from serializing every tool both ways with
`z.toJSONSchema(tool.schema, { io: 'input', reused: ... })`, using the same tool-loading harness as
`services/mcp/tests/unit/tool-schema-snapshots.test.ts`.
