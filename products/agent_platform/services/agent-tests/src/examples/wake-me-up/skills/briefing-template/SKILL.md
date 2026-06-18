---
description: |
  Pinned output schema for the morning briefing markdown file. Defines
  section order, what each section contains, when to omit, and how to tag
  individual items. Load AT THE START of every briefing build so day-to-day
  output looks the same. The user's eye is trained on this shape.
---

# Briefing template

Every morning briefing markdown file lives at `briefings/{YYYY-MM-DD}.md`
and follows this exact structure. **Omit empty sections** — do not
render "no items" placeholders.

```markdown
# Start of day — {YYYY-MM-DD}

> Briefing covers activity since {SINCE timestamp, human-readable}

## 💬 Slack

{Direct asks, customer-call pings, prod incidents, manager DMs.
Hyperlink the source permalink for every item. Skip per-channel
summaries — surface only what asks for the user's attention.}

- {item} — [thread]({permalink})

## 🔍 Review requests

{PRs needing the user's input. Filter to `review_decision ==
REVIEW_REQUIRED`. Group: teammates first, then everyone else.
Anything >24h old gets 🔥. End the section with a link to the
GitHub review queue.}

### From teammates

- 🔥 [#1234 Title]({url}) — @teammate, 2d

### From everyone else

- 🔥 [#9876 Title]({url}) — @rando, 12d

[all review-requested →]({github-review-queue-url})

## 🚀 Your work

{User's open PRs + assigned issues. Anything created since SINCE
gets 🆕. Collapse multi-repo PR trains onto one line — don't list
nine bullets for what's logically one effort.}

### Open PRs ({N})

- 🆕 [#NNNN]({url}) — title (created today)
- [#NNNN]({url}) — title

[all my PRs →]({github-my-prs-url})

## 🎫 Ops

{Escalated tickets only — `priority` of urgent/high, or
`customer_replied` (ball in our court), or aging >7d with
customer as the most recent commenter. Omit the section
entirely if zero. Never show "0 escalated".}

- [Ticket #NNNN]({url}) — title

## 📡 PostHog

{Firing alerts, dashboards trending the wrong way, saved insights
flagged as anomalies. Empty until the user wires up insights.}

- {insight name} — {one-line interpretation} ([view]({url}))

## 📋 Carry-over from yesterday

{Unchecked items from yesterday's briefing, after auto-skip pass
(see `carry-over` skill). Omit section if empty.}

- [ ] Finish migration plan for X
- [ ] Reply to @gustavo's thread
```

## Tagging rules

- **🔥** — review-requested PR >24h. Means a teammate is waiting.
- **🆕** — created or assigned since `SINCE`. Helps the user spot
  the day's new work.
- **No other emoji.** The point is signal; emoji inflation flattens
  the prioritisation.

## What NOT to include

- **No "Today's plan" section.** Don't propose tasks. Surface
  information; let the user decide.
- **No local file path.** Useless on mobile, adds noise.
- **No tool-call traces.** The user sees the report, not the
  investigation.
- **No model self-commentary.** "Here's what I found…" — just
  start with the headers.
