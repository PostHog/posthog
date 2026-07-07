---
description: The data model — the `kudos` table columns, the `kudos_id` dedupe/idempotency scheme, and the per-recipient `people/<handle>.md` profile memory. Load before any table-append or memory-write.
---

# Kudos storage

Two stores, two jobs:

- **`kudos` table** (`@posthog/table-*`) — the deterministic record.
  One row per (recipient, kudos). This is what the weekly digest
  queries. Never enters your context wholesale.
- **`people/<handle>.md` memory** (`@posthog/memory-*`) — a per-person
  highlight reel. Free-form prose, accretes over time. This is what
  answers "what has @jane been recognised for?" without scanning the
  table.

## The `kudos` table

| Column             | Type   | Notes                                                                           |
| ------------------ | ------ | ------------------------------------------------------------------------------- |
| `kudos_id`         | string | **Dedupe key.** See scheme below. Always `dedupe_on: kudos_id`.                 |
| `recipient_handle` | string | Verbatim handle, e.g. `@jane` or `<@U0123>`.                                    |
| `giver_handle`     | string | Verbatim handle of the sender.                                                  |
| `message`          | string | The praise, cleaned.                                                            |
| `themes`           | string | Comma-separated tags, e.g. `teamwork,shipping`. Empty string if none.           |
| `given_at`         | string | ISO 8601 timestamp.                                                             |
| `week`             | string | ISO week of `given_at`, e.g. `2026-W23`. **The weekly digest filters on this.** |
| `source`           | string | `slack` or `chat`.                                                              |
| `permalink`        | string | Slack message link if you have one, else empty string.                          |

### The `kudos_id` scheme — idempotency

Slack retries event deliveries; a thread can resume and re-process.
A stable `kudos_id` + `dedupe_on: kudos_id` makes re-recording a no-op.

- **Slack:** `slack:<channel>:<ts>:<recipient_handle>` — the message
  `ts` from the `[slack]` envelope, suffixed with the recipient so a
  two-person kudos in one message yields two distinct ids.
- **Chat:** `chat:<session_id>:<recipient_handle>` — plus a short
  suffix (`#2`) if the same session records several kudos.

`given_at` and `week` come from the message timestamp, not "now" — a
kudos captured Monday for something said Friday belongs to Friday's
week. For Slack, derive both from the message `ts`.

## The `people/<handle>.md` profile

Path: `people/<handle>.md` where `<handle>` is the recipient handle
lowercased with the leading `@` dropped and `<@U…>` kept as-is but
lowercased (`people/jane.md`, `people/u0123.md`). Keep it stable so a
person maps to exactly one file.

First kudos for a person → `memory-write` to create it:

```markdown
---
description: Kudos profile for @jane
tags: [person, kudos]
---

# @jane

## Highlights

- 2026-06-03 — unblocked the events migration, saved the team a day (from @ben) · _teamwork, above-and-beyond_
```

Later kudos → `memory-read` then `memory-update`, appending one bullet
under `## Highlights`. Keep the newest at the top, cap at ~20 bullets
(trim the oldest); this file is a highlight reel, not an audit log —
the `kudos` table is the complete record.

Writes here are **not** approval-gated (unlike the SRE bot's runbook
corpus) — kudos are low-stakes and high-volume, and a human-in-the-loop
on every "@jane is great" would kill the habit.
