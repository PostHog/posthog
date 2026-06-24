---
description: The Monday digest — how to query last week's kudos, group by recipient, format the celebratory mrkdwn post, and what to do on a quiet week. Load when the weekly cron fires or someone asks for a summary.
---

# Weekly kudos summary

The Monday digest is the product. The table and profiles exist to make
this post good. Keep it warm, scannable, and complete — every kudos
from the week shows up, every recipient is named.

## Which week

The cron fires Monday 09:00 PT. "Last week" is the ISO week **before**
the firing week. The prompt gives you `{fired_at:week}` (the current
week); subtract one to get the target `week` value. E.g. fired in
`2026-W24` → query `week = 2026-W23`.

On-demand ("summarise this month") — widen the filter accordingly
(`week` with an `in: [...]` set, or `given_at` with a `gte`).

## Query

```text
@posthog/table-query
  table: kudos
  where: { week: "2026-W23" }
  order_by: recipient_handle
```

Then group the rows by `recipient_handle` in your head. Use
`@posthog/table-count` if you just want a headline number.

## Format

mrkdwn (Slack flavour — `*bold*`, `_italics_`, `•` bullets). Aim for
scannable: a header, one block per recipient, a light footer.

```text
:tada: *Kudos — week of Jun 1–5* :tada:

*@jane* — 2 kudos
 • unblocked the events migration, saved the team a day _(@ben)_
 • thorough PR review on the billing refactor _(@raj)_

*@raj* — 1 kudos
 • paired for two hours to debug the flaky test _(@jane)_

─────
12 kudos from 8 people this week. Keep 'em coming — just @mention me.
```

Rules:

- **Every recipient, every kudos.** Don't summarise or drop. People
  notice when their shout-out is missing.
- **Attribute the giver** in `_italics_` — recognition is a two-way
  signal.
- **Lead with the busiest recipients** (most kudos first) so the post
  has shape, but never omit the long tail.
- **Footer = a number + a nudge.** The count is social proof; the
  nudge ("@mention me to add one") is how the habit spreads.

## Quiet week

If the query returns zero rows, do **not** post an empty digest. Post
a short nudge instead:

```text
:wave: Quiet week for kudos — nobody got a shout-out. If a teammate
helped you out last week, @mention me with a quick "kudos to @them
for …" and I'll make sure it's celebrated next Monday.
```

One nudge, not a guilt trip. Then end the session.
