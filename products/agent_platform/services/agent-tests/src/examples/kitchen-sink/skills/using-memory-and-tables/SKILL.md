---
description: The two persistence systems — freeform `memory-*` files (prose, the agent's notebook) vs structured `table-*` rows (typed records you query/count/aggregate). When to reach for which, the dedupe/idempotency discipline, and why writes are approval-gated while reads aren't. Load before ANY memory-write / table-append, or when deciding where a new fact belongs.
---

# Using memory and tables

You have two places to put things you want to keep. They are not
interchangeable. Pick deliberately.

## Memory — your notebook (prose)

`@posthog/memory-*` is a tree of markdown files. Free-form, human-shaped,
accretes over time. Reach for it when the thing is **narrative**: a
person's profile, a running log of decisions, a "what I learned about
this team's setup" note. Each file has frontmatter (`description:`) so
search can rank it.

| Tool                        | Use when                                                                    |
| --------------------------- | --------------------------------------------------------------------------- |
| `@posthog/memory-search`    | Find a file by topic/handle when you don't know the exact path. Start here. |
| `@posthog/memory-read`      | Read one file you already have the path for.                                |
| `@posthog/memory-list`      | Browse the tree / see what folders exist.                                   |
| `@posthog/memory-write` ⛔  | Create a new file. **Approval-gated.**                                      |
| `@posthog/memory-update` ⛔ | Append to / revise an existing file. **Approval-gated.**                    |
| `@posthog/memory-delete` ⛔ | Remove a file. **Approval-gated.**                                          |

Conventions:

- **Stable paths.** A thing maps to exactly one file —
  `people/<handle>.md`, `decisions/2026-Q2.md`. Lowercase, no spaces.
  Re-deriving the same path on a second encounter is how you avoid
  duplicate files.
- **Search before you write.** Don't create `people/jane.md` if
  `people/jane.md` already exists — read + update it instead.
- **Keep files tight.** A profile is a highlight reel (~20 bullets,
  newest first), not an audit log. If you need the _complete_ record,
  that's a table, not memory.

## Tables — your ledger (rows)

`@posthog/table-*` is structured, queryable rows with named columns.
Reach for it when the thing is **countable or aggregatable**: events you
log, the `delights` archive, a tally per person. This is what you
`COUNT`, `GROUP BY`, and filter.

| Tool                         | Use when                                              |
| ---------------------------- | ----------------------------------------------------- |
| `@posthog/table-query`       | Pull rows with a filter — "delights from this month". |
| `@posthog/table-count`       | Cheap tallies without dragging rows into context.     |
| `@posthog/table-membership`  | Check whether a key already exists before appending.  |
| `@posthog/table-append`      | Add a row. Always pass `dedupe_on`.                   |
| `@posthog/table-delete` ⛔   | Remove specific rows. **Approval-gated.**             |
| `@posthog/table-truncate` ⛔ | Empty a whole table. **Approval-gated (team admin).** |

Conventions:

- **Always `dedupe_on` a stable id.** Webhooks retry, Slack redelivers,
  threads resume — the same logical row will be appended more than once.
  A deterministic id (e.g. `daily-delight:2026-06-23`) + `dedupe_on`
  makes the re-append a no-op. Never rely on "I probably haven't written
  this yet."
- **One row per fact.** A delight shared to two channels is still one
  delight (one row), not two.
- **Timestamps are the event's time, not "now."** A thing that happened
  Friday belongs to Friday even if you record it Monday.

## Memory vs table — the one-line test

> Will I ever want to **count, group, or filter** these? → **table.**
> Is it **prose a human would read** as-is? → **memory.**

The kudos/delights pattern uses _both_: the table is the complete record
(what you query for the weekly roll-up); the memory file is the readable
per-person highlight reel. That's the canonical "use both" shape.

## Why writes are gated and reads aren't

Reads are safe and frequent — they run immediately. **Writes mutate
durable state**, so `-write`, `-update`, `-delete`, and `-truncate` are
approval-gated. That's deliberate: it's the seam where a human stays in
the loop on what you persist. Don't fight it — when you propose a write,
load **`working-with-approvals`** and narrate the wait cleanly.
