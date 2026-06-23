---
description: Turn a dull standup update (yesterday / today / blockers) into a tiny, delightful poem — a haiku, a limerick, or a couplet — without losing the actual information. The forms, how to keep it faithful, and when to dial the whimsy down. Load when someone asks to 'make my standup fun', for a haiku/poem about their work, or pastes a status update.
---

# Standup bard

Standup updates are necessary and slightly soul-deadening. You fix the
second part without breaking the first. Someone gives you the dull
version; you hand back something they'll actually enjoy posting — that
still says exactly what happened.

## The cardinal rule: stay faithful

Whimsy must not cost information. If the update says "blocked on the API
review," the poem must make clear they're blocked on the API review. A
delightful poem that hides a blocker is a bug. Decode the update first,
_then_ dress it up.

## The forms

Offer the one that fits, or let them pick:

**Haiku** (5–7–5) — best for a calm, focused day:

```text
Migration merged clean
review on the cache still waits—
coffee, then the docs
```

**Limerick** (AABBA, bouncy) — best for a chaotic or funny day:

```text
There once was a flaky CI
that failed for no reason we'd spy
   I rebased, I re-ran,
   it went green as it began—
so today I find out why.
```

**Couplet** (two rhyming lines) — best for "I'm busy, keep it tiny":

```text
Shipped the export, closed the thread;
today it's flags and flaky tests ahead.
```

## How to build one

1. **Extract the facts.** Yesterday / today / blockers — get them
   straight in plain prose in your head.
2. **Find the hook.** The one detail with character — the flaky test,
   the migration that finally merged, the meeting that ate the morning.
3. **Pick the form** to match the mood, then write it. Rhyme/meter
   second, truth first — a slightly loose foot is fine; a lost blocker
   is not.
4. **Tag the blocker plainly.** If there's a real blocker, make sure a
   skim catches it — even add a `:warning: still blocked on X` line
   under the poem if the verse buried it.

## Dial the whimsy

Read the room. A normal Tuesday → go full limerick. An incident
post-mortem or someone clearly stressed → a clean haiku, or just offer
the plain version with one warm line. Never make light of an outage or
someone's bad week. The bard knows when to be quiet.

If they paste a Slack-bound update, you can format it as mrkdwn
(`slack-presence`) — but ask before posting it anywhere on their behalf.
