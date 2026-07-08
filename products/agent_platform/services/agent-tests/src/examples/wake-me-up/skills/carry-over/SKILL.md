---
description: |
  Pulling unchecked items from yesterday's briefing forward into today's,
  while filtering out anything that's already resolved by the new data.
  Load early in the briefing build — it's step 2 of the main loop.
---

# Carry-over

The user shouldn't have to look at items they already finished. Each
morning, sweep yesterday's briefing and bring forward what's still
genuinely open.

## How to find yesterday's briefing

```text
@posthog/table-query {
  table: "briefings",
  order_by: "date",
  desc: true,
  limit: 2,
}
```

Returns the two most recent rows. If the most recent is today's
(possible on a re-run), use index 1 instead of 0. If there are
fewer than two rows, skip carry-over entirely — this is the user's
first run.

Then `@posthog/memory-read` the `path` from that row to get the full
markdown.

## Extract unchecked items

Regex against the markdown body: every line matching `^- \[ \]` is
a candidate. Preserve the original text including the link, since
the user wants the same hyperlink that worked yesterday.

## Filter resolved items

For each candidate, check whether the current step-3 data shows
it's already done. Common patterns:

- **PR review carry-over** — "Review [#1234](…)" → drop if #1234
  is no longer in today's `review_requested` list (means it merged,
  closed, or you reviewed it).
- **Ticket carry-over** — "Triage [#5678](…)" → drop if today's
  Zendesk data shows status moved off `new`/`pending` (someone
  else picked it up).
- **Action carry-over** — "Reply to @gustavo's thread" → harder
  to verify automatically. **When in doubt, keep.** A duplicate
  item is annoying; a missed open task is worse.

## How to render carry-over

Put it under the `## 📋 Carry-over from yesterday` section in
today's markdown. Use the same `- [ ]` checkbox shape so the user
can mark progress and the next day's carry-over picks it up
naturally.

If after filtering there are zero items left, **omit the section
entirely** — don't render "Carry-over: none". The user infers from
the absence.

## Edge case: long gaps

If yesterday's briefing is >3 days old (weekend, vacation), include
a `> Catching up after {N} days off — items here may be stale`
note above the carry-over list. The user wants to be reminded that
the context is from before their break.
