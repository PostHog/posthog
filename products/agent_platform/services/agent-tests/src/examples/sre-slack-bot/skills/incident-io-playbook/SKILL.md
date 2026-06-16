---
name: incident-io-playbook
description: How to query and update incident.io — list active incidents, fetch context for an incoming webhook, post triage updates, and (rare) open a new incident. Load when an incident.io webhook fires the agent, when an alert correlates to an active incident, or when recording a resolved outcome.
---

# Skill — incident.io playbook

incident.io is the source of truth for what counts as an "incident" at
the company. The Slack thread is where humans coordinate; incident.io
is the timeline + post-mortem record. Your job here is to keep both
in sync so neither tells the wrong story afterwards.

You do **not** declare incidents on your own. Opening a new incident
is escalation — humans do that. The one exception is documented below.

## Auth

Every call is to `https://api.incident.io/v2/...` with:

```text
Authorization: Bearer ${INCIDENT_IO_TOKEN}
```

The token lives in `spec.secrets` as `INCIDENT_IO_TOKEN`; the runner
substitutes the resolved value before dispatch. If you get back
`secret_not_resolved: INCIDENT_IO_TOKEN`, the agent isn't configured
for incident.io — say so plainly in-thread, skip the incident.io steps,
and continue with the Slack-only flow.

All responses have an `incident` (singular) or `incidents` (list)
key plus a `pagination_meta` block. Errors come back with a 4xx /
5xx and `{ "type": "validation_error", "errors": [...] }` — check
the HTTP status before treating the body as success.

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
@posthog/http-request {
  url: "https://api.incident.io/v2/incidents/01HXYZ...",
  method: "GET",
  headers: { "Authorization": "Bearer ${INCIDENT_IO_TOKEN}" }
}
```

The response carries `incident.slack_channel_id` (use this as
`channel` in subsequent Slack calls) and
`incident.slack_team_id` (sanity-check against your `trusted_workspaces`
config).

## When you're triggered from Slack and want to check incident.io

If you're investigating an alert in Slack and want to know whether
there's already an active incident covering it, list active incidents
and grep titles + reference codes:

```text
@posthog/http-request {
  url: "https://api.incident.io/v2/incidents?status_category%5Bone_of%5D=active&page_size=25",
  method: "GET",
  headers: { "Authorization": "Bearer ${INCIDENT_IO_TOKEN}" }
}
```

> **URL-encoding note.** incident.io's filter syntax uses square
> brackets (`status_category[one_of]`). The `@posthog/http-request`
> tool runs the URL through strict URI validation, which rejects raw
> `[` / `]` — percent-encode them as `%5B` / `%5D` (as shown above).
> Same rule for any filter param: `?incident_role[one_of]=lead`
> becomes `?incident_role%5Bone_of%5D=lead`.

If one matches your alert signature (substring match on `name`,
`summary`, or any of the `incident_role_assignments`), mention it
in your reply with the `reference` field (e.g. `INC-42`) so the
human can jump straight to the existing incident. **Don't open a
new one** — the right move is to link.

## Posting a triage update to an incident

This is the main write you do. Use it when you've finished gathering
evidence and want the hypothesis on the incident timeline (not just
the Slack thread):

```text
@posthog/http-request {
  url: "https://api.incident.io/v2/incidents/01HXYZ.../updates",
  method: "POST",
  headers: { "Authorization": "Bearer ${INCIDENT_IO_TOKEN}" },
  body: {
    "incident_id": "01HXYZ...",
    "message": "Triage from the SRE bot:\n\n*TL;DR:* ingest 500s correlate with kafka consumer lag (5x baseline since 14:32 UTC).\n\n*Evidence:* error rate 0.2%→4.7% at 14:32; consumer-lag query in PostHog shows lag climbing from 1k→18k msgs on `events-main`; runbook https://runbooks.internal/ingestion-500s names this exact pattern.\n\n*Suggested next step:* scale `events-main` consumer group from 12 → 18 pods. cc @oncall.",
    "new_incident_status_id": null,
    "severity_id": null
  }
}
```

Keep `new_incident_status_id` and `severity_id` as `null` unless a
human has explicitly asked you to transition the incident. You
provide information; humans drive status.

The same content also goes in your Slack reply per
`slack-thread-protocol`. Don't pick one over the other — they have
different audiences and lifespans.

## Recording a resolved outcome

When the incident is acknowledged as resolved in the Slack thread,
do **two** things:

1. Append a row to the `incidents` memory table (as documented in
   `agent.md`) — this is for **your** future pattern-matching.
2. Post a final update to the incident.io timeline summarising the
   root cause + mitigation:

```text
@posthog/http-request {
  url: "https://api.incident.io/v2/incidents/01HXYZ.../updates",
  method: "POST",
  headers: { "Authorization": "Bearer ${INCIDENT_IO_TOKEN}" },
  body: {
    "incident_id": "01HXYZ...",
    "message": "*Resolved.*\n\n*Root cause:* kafka consumer-group `events-main` was under-provisioned after the morning deploy bumped consumer concurrency.\n\n*Mitigation:* scaled the group 12→18 pods; lag drained in 4m; error rate back to baseline by 14:42 UTC.\n\n*Follow-ups:* (1) raise the autoscaler floor for `events-main`; (2) add a pre-deploy check that compares advertised vs configured concurrency."
  }
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
@posthog/http-request {
  url: "https://api.incident.io/v2/incidents",
  method: "POST",
  headers: { "Authorization": "Bearer ${INCIDENT_IO_TOKEN}" },
  body: {
    "idempotency_key": "<alert_signature>:<startsAt>",
    "name": "<alert name> — auto-opened by SRE bot",
    "summary": "<one-paragraph context from the alert>",
    "severity_id": "<critical-severity-id-from-config>",
    "mode": "real",
    "visibility": "public",
    "incident_type_id": null
  }
}
```

Two things to note:

- The `idempotency_key` is critical — without it, retries from the
  webhook would duplicate incidents. Derive it deterministically
  from the alert signature + start time.
- `severity_id` and `incident_type_id` are organisation-specific
  IDs. Read them from `@posthog/memory-read incident-io-config.md`
  if that file exists; otherwise reply in Slack with "I would open
  an incident but I'm missing the severity-id config" and stop.
  Don't guess.

The very next thing you do after opening is post a Slack reply
linking to the new incident's `permalink`, so humans can take over.

## Errors to handle explicitly

- `401 / authentication_error` — `INCIDENT_IO_TOKEN` is wrong or
  revoked. Reply in Slack: "incident.io auth failed, someone needs
  to rotate `INCIDENT_IO_TOKEN`" and stop.
- `429` — rate-limited. Back off — the next webhook invocation will
  retry. Don't loop.
- `validation_error` — your body shape is wrong. Inspect the
  `errors[]` array and fix; don't retry blindly with the same body.

## What you don't do

- **You don't add post-mortem actions.** Those are a human's
  reflection, not yours. You record what happened; the team
  decides what to learn from it.
- **You don't assign roles.** `incident_lead`, `comms_lead`, etc.
  are human-to-human assignments.
- **You don't change severity.** If you think the severity is
  wrong, say so in the Slack reply and let a human flip it.
