---
name: incident-io-playbook
description: How to work incident.io through its connected MCP — list active incidents, fetch context for an incoming webhook, post triage updates, and (rare) open a new incident. Load when an incident.io webhook fires the agent, when an alert correlates to an active incident, or when recording a resolved outcome.
---

# Skill — incident.io playbook

incident.io is the source of truth for what counts as an "incident" at
the company. The Slack thread is where humans coordinate; incident.io
is the timeline + post-mortem record. Your job here is to keep both
in sync so neither tells the wrong story afterwards.

You do **not** declare incidents on your own. Opening a new incident
is escalation — humans do that. The one exception is documented below.

## How you reach incident.io

incident.io is a **connected MCP**, not a token. The `incident-io`
entry in `spec.mcps[]` is an agent-level connection: the owner links
incident.io once and every asker reuses that one credential. The MCP's
tools (`incident_list`, `incident_show`, `incident_update`,
`incident_create`, `alert_list`, …) appear inline — call them by name;
there's no URL to build and no `${...}` secret to substitute.

If the MCP **isn't connected** — a fresh project ships a placeholder
connection, so the incident.io tools may be unavailable or come back as
errors — say so plainly in-thread, skip the incident.io steps, and
continue with the Slack-only flow. Don't fail the session.

## When you receive an incident.io webhook

The webhook trigger fires the agent with the incident.io payload as
the seed message. The shape is:

```json
{
  "event_type": "public_incident.incident_updated_v2",
  "data": { "id": "01HXYZ...", "name": "...", "status": "...", "severity": "..." }
}
```

Look at `event_type`:

- `public_incident.incident_created_v2` — new incident, you're being
  pulled in for early triage. Acknowledge in the incident's Slack
  channel and start the standard triage loop.
- `public_incident.incident_updated_v2` — existing incident changed.
  Only re-engage if the status moved to `investigating` or the
  severity escalated. Otherwise this is noise — end the session.
- Anything else — end the session.

Always fetch the full incident first to get the Slack channel +
current status, even if the webhook payload looks complete:

```text
incident_show { id: "01HXYZ...", include: ["investigation"] }
```

The response carries the incident's Slack channel (use it as
`channel` in subsequent Slack calls) and its current status. Request
`include: ["investigation"]` whenever you're triaging a root cause —
it carries the AI investigation findings.

## When you're triggered from Slack and want to check incident.io

If you're investigating an alert in Slack and want to know whether
there's already an active incident covering it, list active incidents
and grep titles + reference codes:

```text
incident_list { status_category: ["active"], page_size: 25 }
```

You can narrow with `query` (a free-text search across incident
names), or enrich each result with `include: ["summary"]` to match on
the summary without a follow-up `incident_show`.

If one matches your alert signature (substring match on `name`,
`summary`, or the role assignments), mention it in your reply with the
`reference` field (e.g. `INC-42`) so the human can jump straight to the
existing incident. **Don't open a new one** — the right move is to link.

## Posting a triage update to an incident

This is the main write you do. Use it when you've finished gathering
evidence and want the hypothesis on the incident timeline (not just
the Slack thread). `incident_update` takes a `message` that posts to
the incident channel + timeline:

```text
incident_update {
  id: "01HXYZ...",
  message: "Triage from the SRE bot:\n\n*TL;DR:* ingest 500s correlate with kafka consumer lag (5x baseline since 14:32 UTC).\n\n*Evidence:* error rate 0.2%→4.7% at 14:32; consumer-lag query in PostHog shows lag climbing from 1k→18k msgs on `events-main`; runbook https://runbooks.internal/ingestion-500s names this exact pattern.\n\n*Suggested next step:* scale `events-main` consumer group from 12 → 18 pods. cc @oncall."
}
```

Pass **only** `message` — leave `incident_status_id` and `severity_id`
unset unless a human has explicitly asked you to transition the
incident. You provide information; humans drive status.

The same content also goes in your Slack reply per
`slack-thread-protocol`. Don't pick one over the other — they have
different audiences and lifespans.

## Recording a resolved outcome

When the incident is acknowledged as resolved in the Slack thread,
do **two** things:

1. Append a row to the `incidents` memory table (as documented in
   `agent.md`) — this is for **your** future pattern-matching.
2. Post a final `incident_update` to the incident.io timeline
   summarising the root cause + mitigation:

```text
incident_update {
  id: "01HXYZ...",
  message: "*Resolved.*\n\n*Root cause:* kafka consumer-group `events-main` was under-provisioned after the morning deploy bumped consumer concurrency.\n\n*Mitigation:* scaled the group 12→18 pods; lag drained in 4m; error rate back to baseline by 14:42 UTC.\n\n*Follow-ups:* (1) raise the autoscaler floor for `events-main`; (2) add a pre-deploy check that compares advertised vs configured concurrency."
}
```

You do **not** close the incident yourself — that's a human-driven
state transition. The final update is your hand-off, not the
ribbon-cutting.

## When (and only when) to open a new incident

You **almost never** open incidents. The exception, narrowly
scoped:

- The alert is `severity: critical`, **and**
- No active incident in the list above matches, **and**
- The Slack thread has been quiet for ≥5 minutes with no human
  acknowledgement.

In that case:

```text
incident_create {
  name: "<alert name> — auto-opened by SRE bot",
  summary: "<one-paragraph context from the alert>",
  severity_id: "<critical-severity-id-from-config>"
}
```

Two things to note:

- `incident_create` defaults to **triage** if you omit `severity_id`,
  and **never invent a severity** — only pass `severity_id` when the
  alert is unambiguously critical and you have the org's id. Leaving it
  unset lets a responder set severity when they accept the incident.
- `severity_id` is organisation-specific. Read it from
  `@posthog/memory-read incident-io-config.md` if that file exists;
  otherwise reply in Slack with "I would open an incident but I'm
  missing the severity-id config" and stop. Don't guess.

The very next thing you do after opening is post a Slack reply linking
to the new incident (use its `reference`, e.g. `INC-99`), so humans can
take over.

## Errors to handle explicitly

- **MCP not connected / tools unavailable** — the `incident-io`
  connection is still the placeholder, or the link was revoked. Reply
  in Slack that incident.io isn't connected for this agent, skip the
  incident.io steps, and continue Slack-only. Don't fail the session.
- A tool call comes back as an error — inspect the message and fix the
  arguments; don't retry blindly with the same shape. If it's a
  validation error (e.g. a missing required field), the response names
  the field — supply it or hand the link back to a human rather than
  resolving catalog IDs yourself.

## What you don't do

- **You don't add post-mortem actions.** Those are a human's
  reflection, not yours. You record what happened; the team
  decides what to learn from it. (`follow_up_create` exists on the
  MCP, but adding follow-ups is a human call.)
- **You don't assign roles.** `incident_lead`, `comms_lead`, etc.
  are human-to-human assignments.
- **You don't change severity.** If you think the severity is
  wrong, say so in the Slack reply and let a human flip it.
