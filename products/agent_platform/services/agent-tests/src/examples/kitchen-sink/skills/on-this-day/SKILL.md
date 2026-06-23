---
description: The daily-delight ritual the cron fires (and anyone can ask for) — fetch one genuinely interesting thing that happened on today's calendar date, write it to the `delights` table, and post a short, charming Slack note. The output recipe + the 'don't be boring' bar. Load when the daily-delight cron fires or someone asks for today's delight / 'this day in history'.
---

# On this day

Once a weekday morning the `daily-delight` cron wakes you with a date.
Your job: find one genuinely interesting thing that happened on this
calendar day, archive it, and post a small dose of delight. People
should look forward to it.

## The ritual

1. **Get the date.** The cron prompt carries `{fired_at:date}`. For an
   on-demand ask, use today (or the date they name).
2. **Check the archive first.** `@posthog/table-membership` (or
   `table-query`) on `delights` for this date's id
   (`delight:<YYYY-MM-DD>`). If it's already there, **re-post the
   stored one** and stop. Idempotency: the cron can fire twice
   (catch-up), and you must not post two different delights for one day.
3. **Get a fact** — and mind the gate:
   - **On-demand (a human is here):** `@posthog/http-request` a public
     "this day in history" source. It's approval-gated — one tap and
     you're reading (see `reaching-the-internet`). Pick something
     _surprising_ — a first, an invention, an oddity, a born-on-this-day
     worth knowing. Skip the rote ("a war started"). One fact, well
     chosen.
   - **Unattended cron:** nobody's there to approve a live fetch, so
     **don't fetch** — compose an evergreen delight from what you know
     (history is full of them), or re-post the most recent stored one
     with a light "from the vault" framing. Never let the cron park on a
     gated call waiting for an approval that isn't coming.
4. **Record it.** `@posthog/table-append` to `delights`,
   `dedupe_on: delight_id`.
5. **Post it.** `@posthog/slack-post-message` to the delights channel —
   the short, charming version (recipe below).

## The `delights` table

| Column       | Notes                                                        |
| ------------ | ------------------------------------------------------------ |
| `delight_id` | `delight:<YYYY-MM-DD>`. **Dedupe key.**                      |
| `date`       | `YYYY-MM-DD`.                                                |
| `headline`   | One-line hook, e.g. "The first emoji was born today (1999)." |
| `blurb`      | 1–2 sentences of why it's neat.                              |
| `source_url` | Where you found it.                                          |

## The output recipe (Slack)

```text
:sparkles: *On this day* — <year>

*<headline>*
<one or two sentences that make it land — a detail, a number, a
"and that's why we have X today">

<https://source|where I got this>
```

## The "don't be boring" bar

- **Surprise > importance.** "The longest game of Monopoly lasted 70
  days" beats "a treaty was signed."
- **One fact.** A wall of three facts is a worse delight than one good
  one.
- **A detail makes it.** The number, the name, the twist. "An inventor
  patented X" is forgettable; "patented X, then forgot to renew it and
  lost a fortune" sticks.
- **Land the why.** End on what it means or where it echoes today.

If the fetch comes back dry or the day is genuinely thin, a charming
"slow day in history — so here's an evergreen oddity instead: …" beats a
limp factoid. Never post nothing; never post boring.
