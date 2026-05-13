# Report template

The skill produces two outputs: a short headline roast printed inline in chat,
and a full audit written to `./roast-my-funnel-{YYYY-MM-DD}.md`. Both are
generated together — the chat preview is a subset of the file.

## Chat preview (printed inline in the assistant reply)

Keep this **short**. The point is impact, not completeness. The full report is
the file.

```markdown
🎤 **Roast: {funnel name}**

> {one-line zinger in the user's chosen tone}

**The crime:** {worst step} drops {X%} of users — {key supporting number}.
**The fix:** {top-priority fix in one sentence}.

Full audit written to `./roast-my-funnel-{date}.md`.
```

Voice matches the wizard's roast level per [roast-voice.md](./roast-voice.md).
If the user didn't pick a level, default to "honest."

## Full report (written to file)

````markdown
# Roast: {funnel name} — {YYYY-MM-DD}

**Funnel:** [{name}](/insights/{short_id})
**Window:** {N} days **Roast level:** {gentle / honest / merciless}
**Comparison:** {prior period / sibling funnels / none}

## 🎤 The headline

> {The same zinger that was printed in chat.}

## The crime

**Step:** {step number} — `{step event}`
**Drop:** {N} users in, {M} users out → **{X% conversion}**, losing {N-M} users.
{If revenue-weighted: Estimated lost value: ${Z}.}

**Why this step qualifies as the worst:**

- Highest {absolute drop / relative drop / revenue-weighted drop} in the funnel
- {Comparator from comparison mode, if applicable}
- See §A.1 for the funnel breakdown.

## Why it's happening

Ranked hypotheses, highest confidence first. Each grounded in a query result.

### 1. {Hypothesis name} — {high / medium / low} confidence

**Why we think so:**

- {Evidence — specific number from the analysis}
- {Second piece of evidence if any}
- See §A.{n}.

**What it means in practice:**
{One-sentence translation of the hypothesis into the user's reality.}

### 2. {Next hypothesis}

(...same structure)

### Ruled out

- **{Hypothesis name}** — {why the data doesn't support it}. See §A.{n}.

## Fixes

Listed in priority order. Each fix is concrete enough to assign to someone.

### Fix 1 — {short title}

- [ ] {Specific change to make}
- [ ] {Tracking gap to close, if any}
- [ ] {Where to make the change — URL, component, settings page}

**Expected effect:** {one sentence on the mechanism — why this should move the metric}

{If wizard requested A/B tests:}

**How to validate:**

- **Hypothesis:** {what you expect to happen}
- **Variants:** Control = current; Treatment = {described change}
- **Primary metric:** {metric to read out}
- **Minimum cohort size:** {rough order of magnitude based on current step volume}

### Fix 2 — {short title}

(...same structure)

## Honorable mentions

Other weak steps in the funnel. No zingers, just facts.

- **Step {n} — `{event}`** — {X% drop}. {One-line reason it's not the worst}.
- ...

## What you got right

At least one positive observation. Pulled from the data.

- {Step / segment / configuration that's performing well, with the number that supports it.}

## Data gaps

What couldn't be measured and why.

- {Gap} — {missing event / property / source}. To unlock, {specific instrumentation suggestion}.

## Appendix — queries

### §A.1 — Step-by-step drop

```sql
{HogQL run, with substitutions resolved}
```

Result summary: {key numbers}

### §A.2 — Time-to-next-step

```sql
...
```

(...one entry per analysis run)
````

## Edge-case template — funnel is fine

Use when the worst step's drop is below the sanity threshold (<5%) or the
funnel has high conversion overall.

```markdown
# Roast: {funnel name} — {YYYY-MM-DD}

## 🎤 Not much to roast here

> {gentle observation — there's no zinger because the data doesn't support one}

**Overall conversion:** {X%} over {window}.
**Worst step:** {step name} — {Y%} drop, which is within normal range for a
funnel this length.

## What we looked at

(...standard sections, but the "fixes" section is replaced by:)

## Marginal improvements worth considering

- {Small thing 1, if any}
- {Small thing 2, if any}

If you wanted us to find a serious problem, there isn't one in this funnel right
now. That's worth knowing too.
```

## Edge-case template — no traffic

Use when the funnel has 0 users entering it in the window.

```markdown
# Roast: {funnel name} — {YYYY-MM-DD}

## 🎤 Can't roast a funnel that's empty

Zero users entered this funnel in the last {window} days. Possible reasons:

- **Tracking:** the step 1 event isn't firing. Check the SDK and the event name.
- **Wrong event:** the event exists but the funnel definition points at a typo or
  a deprecated name. Check `posthog:read-data-schema`.
- **Audience filters:** the funnel has a filter that excludes everyone. Review
  the insight's `properties` filter.
- **Recent funnel, no traffic yet:** if step 1 was instrumented this week, give
  it time.

Re-run the skill once at least step 1 is firing.
```

## Formatting rules

- The chat preview uses 4-backtick fences if it ever needs to nest a code block;
  the inline roast itself rarely needs code.
- The full report uses 3-backtick fences inside the outer markdown example block
  (which uses 4-backtick fences) — see this file's structure for the pattern.
- Use markdown checkboxes (`- [ ]`) for fix action items.
- Inline-link insights with short_id paths: `[Name](/insights/{short_id})`.
- The 🎤 emoji is the only emoji in the report — it's the brand mark of the roast.
  No other emojis.
- Cap the report at ~3 hypotheses and ~3 fixes. More than that and the user
  stops reading.
