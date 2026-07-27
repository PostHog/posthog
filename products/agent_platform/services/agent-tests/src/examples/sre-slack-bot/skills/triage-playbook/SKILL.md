---
name: triage-playbook
description: Structured triage flow — phases for context gathering, hypothesis, and reporting. Load when starting an investigation.
---

# Skill — triage playbook

A structured flow for the first 5 minutes of any investigation.
Walk through every phase. Skipping ahead to "post a fix" without
evidence is the most common failure mode.

## Phase 1 — context (timebox: 2 min)

Gather the facts before forming any hypothesis.

1. **What fired?** Read the alert payload (webhook) or the engineer's
   message (Slack). Extract:
   - The service / component name.
   - The metric or condition that tripped (error rate? latency?
     queue depth? a specific log pattern?).
   - The threshold and the observed value, with units.
   - The time window.
2. **Where in the stack?** Is this the ingestion path, the query
   path, the web app, a background worker, the database, an external
   provider? Knowing the layer narrows the hypothesis space.
3. **What's the blast radius?** Is this affecting one team, one
   region, all customers, internal users only? Look for clues in the
   alert labels and any recent Slack messages.

If any of these are unclear from the trigger payload, **read the
Slack thread or channel for the last ~15 min of context** before
querying PostHog data. Humans usually said something useful nearby.

4. **Is there already an incident for this?** Before forming any
   hypothesis, query incident.io for active incidents (see
   `incident-io-playbook`). If one already covers what you're
   looking at, your job for this session is to **link to it** and
   then join the conversation in that incident's Slack channel —
   not to investigate in parallel. Two threads on the same incident
   is worse than one.

## Phase 2 — evidence (timebox: 3 min)

For each candidate hypothesis, pick **one query that would
distinguish it from the alternatives**, run it, and look at the
result before moving on.

Common query shapes:

- **Volume regression** — compare event counts in the last 15 min
  to the same window 1 hour and 24 hours ago. A drop suggests
  ingestion problem; a spike suggests downstream pressure or a bug
  loop.
- **Error rate by team** — `count() group by team_id` filtered to
  the failing event. Concentrated on one team → check that team's
  config; spread across many → check the platform.
- **Recent deploys** — query for `$pageview` of internal "deploy
  marker" pages or check Git for merges within the alert window.
- **Correlated services** — if `service A` is failing, run a query
  on `service B` (its upstream) in the same window. If both are
  hot, the problem is upstream of A.

Don't run more than 4-5 queries per investigation. Each one costs
time and burns context. If you're 5 queries in with no signal, the
right move is to surface what you've tried and ask the human.

## Phase 3 — hypothesis + report (timebox: 1 min)

Form one (or at most two) specific hypotheses. Each one should have
the shape:

> **Hypothesis:** \[component\] is failing because \[mechanism\],
> evidenced by \[specific query result / log snippet / runbook
> reference\]. Confidence \[high / medium / low\] because
> \[reasoning\].

If confidence is **low**, name explicitly what would raise it
(usually: a Grafana metric you can't query, a `kubectl describe`
output, or a log line from a service that doesn't ingest to
PostHog).

Then load the `slack-thread-protocol` skill to format the report
and post it.

## When to break the flow

- **Symptom is escalating.** If the alert says "error rate climbing"
  and your first query shows it's still climbing, **post that fact
  immediately** before you finish investigating — pinging humans
  early matters more than completing your analysis.
- **You hit a wall on permissions.** If a hypothesis needs data
  you can't reach (production secrets, k8s, customer data outside
  PostHog), say so and stop. Don't pretend.
- **The alert was a false positive.** If the data shows the trigger
  was noise (e.g. a 1-minute blip that already recovered), post a
  "this resolved itself" reply with the evidence, then end the
  session. Don't waste anyone's attention.
