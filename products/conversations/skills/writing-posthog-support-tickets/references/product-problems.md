# Problems with a feature

Many tickets start as "this looks wrong": uneven experiment exposures, events that never arrived, a missing recording, or a count that doesn't match their own database.
Most have a cause in the person's setup that their own data shows, and the product's diagnosis finds it faster than a ticket would.
So investigate the way that product's support engineer would, and write a ticket only for what is left.

## Run the product's diagnosis

Find the product's skill with `learn -s "<the problem in a few words>"`, such as "experiment exposures uneven" or "recordings missing", and follow it on the person's data.

- When it finds the cause, give the person the cause, the fix and the numbers that show it, and write no ticket.
- When the fix changes live data or what users see, such as an edit to a running experiment, the person decides whether to make it. That is still not a ticket.
- When it rules out every cause it knows, or traces the cause to PostHog's side, write the ticket.
- When no skill matches, check what support would: the object's settings and its activity log, the raw events behind the number, and the SDK and its version.

## What the ticket carries

Support starts from your numbers, so give them the ones that led to your conclusion:

- The object: its link, and the setting that matters, such as the flag key and the configured split.
- What they see and what they expected, as numbers, with the time range in UTC.
- Each check you ran and what it showed. Keep the ones that ruled a cause out, so support doesn't run them again.
- The question only PostHog can answer, such as what the flag service returned to the people recorded on the wrong variant.

Leave out the queries behind your checks, unless support needs one to reproduce a number.

## Example

The diagnosis confirmed a sample ratio mismatch and put it on the assignment side, but found no cause in the person's setup.

```text
Request: Our experiment "Checkout button copy" has a sample ratio mismatch: on a 50/50 split, 10,412 people saw control and 8,960 saw test from Oct 5, 2026 to Nov 2, 2026.
1. Why are 790 people whose hash assigns them to test recorded in control?
2. What did the flag service return to those people?

Details:
- Project: Web app, ID 12345, US Cloud, https://us.posthog.com/project/12345
- Experiment: https://us.posthog.com/project/12345/experiments/678, flag `checkout-button-copy`, 50/50, multiple-variant handling set to first seen
- SDK: posthog-js 1.290.0, flag read in the browser, with no bootstrap and no local evaluation

Already checked:
- Claude Code checked: chi-squared p < 0.0001 on exposed people, against the configured 50/50
- Claude Code checked: recomputing the assignment hash puts the gap on the assignment side, with 790 people recorded in control who hash to test
- Claude Code checked: the activity log shows no change to the flag's split, conditions or variants since Oct 5, 2026
- Claude Code checked: 1.02 distinct IDs per person, and 0.04% of exposed people saw both variants
```
