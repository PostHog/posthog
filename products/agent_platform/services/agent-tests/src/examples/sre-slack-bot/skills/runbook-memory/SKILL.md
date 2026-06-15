# Runbook memory — read, curate, propose

Your durable knowledge lives in **agent memory**, organised as a
runbook corpus. This is what lets you get better over time: every
resolved incident, every "here's how this system actually works"
aside from an engineer, every recurring procedure — captured once,
recalled forever.

Two halves to this skill:

1. **Reading** the corpus to ground your triage (open, no approval).
2. **Proposing** new or updated runbooks on a user's behalf — which
   is **approval-gated**, so you queue the change and link the user
   to where they approve it.

---

## The corpus layout

Every runbook is a markdown memory file under `runbooks/`. Three
folders, each with a distinct job. Put a file in exactly one:

| Folder                 | Holds                                                                                          | Path shape                       |
| ---------------------- | ---------------------------------------------------------------------------------------------- | -------------------------------- |
| `runbooks/alerts/`     | What to do when a **specific alert** fires — one file per alert signature. Grows per incident. | `runbooks/alerts/<signature>.md` |
| `runbooks/systems/`    | How a **subsystem works** — architecture, dependencies, dashboards, owners, failure modes.     | `runbooks/systems/<area>.md`     |
| `runbooks/procedures/` | Reusable **operational procedures** not tied to one alert — rollback, scaling, draining.       | `runbooks/procedures/<task>.md`  |

Pick the folder by asking "what is this knowledge _about_?":

- "When `ingestion-500s` fires, check X then Y" → `runbooks/alerts/ingestion-500s.md`
- "The ingestion pipeline is Kafka → plugin-server → ClickHouse, owned by #team-ingestion" → `runbooks/systems/ingestion.md`
- "How to scale the events consumer group" → `runbooks/procedures/scale-consumer-group.md`

The path **is** the identity. Use the same `<signature>` you derive
for the `incidents` table so the alert runbook and the tabular row
line up. Lowercase, `a-z 0-9 _ - /` only, end in `.md`.

> The `incidents` **table** (tabular memory) and the `runbooks/alerts/`
> **prose** are complementary, not duplicates. The table is the fast
> structured lookup ("have we seen this exact signature → row").
> The alert runbook is the human-readable judgement that table cells
> can't hold: the diagnosis tree, the false leads, the escalation path.

---

## Reading the corpus during triage

Do this at the **start** of an investigation, right after you've
derived the alert signature — before you start querying logs.

1. `@posthog/memory-search` with the signature + symptom as the cue,
   `prefix: "runbooks/"`. Cheap, returns the most relevant files
   with a snippet.
2. If a hit looks on-point, `@posthog/memory-read` it in full. An
   `runbooks/alerts/<signature>.md` hit means you've likely seen this
   class of alert — lead your first reply with its known causes +
   checks so the human can short-circuit.
3. Pull the relevant `runbooks/systems/<area>.md` too when the alert
   touches a subsystem you have notes on — owners and dashboards
   there save round-trips.

Cite the runbook you used (path) in your reply, the same way you
cite a log line or query. If the corpus is empty for this signature,
that's a signal there's a runbook worth proposing once you resolve it.

---

## Writing a GOOD runbook

A runbook is only worth the tokens to read it if it's specific,
current, and skimmable. Hold yourself to these:

**Structure — `runbooks/alerts/<signature>.md`:**

```markdown
# Alert: <signature>

**What it means:** one sentence — what's actually degraded when this fires.

## First checks (in order)

1. <the single most diagnostic query/dashboard, with the exact HogQL or URL>
2. <next>

## Known causes

- **<cause>** → symptom looks like <X>. Mitigation: <Y>. (seen <date>, <thread>)

## Escalation

- Owner: <#team / @person>. Page only if <condition>.

## Not this

- <false lead that wasted time before, so the next person skips it>
```

**Structure — `runbooks/systems/<area>.md`:** architecture (1 paragraph
or a small diagram) → upstream/downstream dependencies → the 2-3
dashboards/queries that matter → owners → known failure modes.

**Quality bar — applies to every entry:**

- **One concept per file.** If you're tempted to write "and also…",
  that's a second file. Small files search better and update cleanly.
- **Specific over general.** Exact query, exact dashboard URL, exact
  threshold. "Check the logs" helps no one; the precise HogQL does.
- **Set a sharp `description`.** It's the only thing search and the
  list view show. "Alert runbook: ingestion 500s — Kafka lag is the
  usual cause" beats "ingestion notes".
- **Tag for recall.** `tags: ["ingestion", "kafka", "alert"]`.
- **Date the evidence.** "(seen 2026-05-29, <thread_url>)" so a
  reader can judge whether it's still current.
- **Prefer update over append-forever.** When you learn the cause was
  actually Z, _refine_ the "Known causes" section — don't bolt a
  contradicting note on the end. Stale runbooks are worse than none.

**Read before you write.** Always `memory-read` (or rely on a search
hit) the existing file first. If it exists, propose a `memory-update`
that folds in the new lesson; only `memory-write` a fresh file when
nothing covers it. Two files for the same signature is the failure
mode to avoid.

---

## Proposing a change (the approval gate)

You don't get to silently rewrite institutional knowledge. Both
`@posthog/memory-write` and `@posthog/memory-update` are
**approval-gated**: when you call one, the dispatcher returns a
synthetic `queued` envelope instead of writing, and a human approves
(and may edit) the change before it lands.

### When to propose

- **After a resolution** — once an incident is acknowledged fixed
  in-thread, capture the lesson: new alert runbook, or an update to
  the existing one with the confirmed cause + mitigation.
- **When an engineer hands you durable knowledge** — "FYI the events
  consumer is what lags first under load" → propose a
  `runbooks/systems/` note.
- **When a runbook is wrong or stale** — propose the correction.

Don't propose for one-off chatter, speculation, or anything still
unconfirmed. A runbook asserts something true.

### Recognising the queued envelope

```jsonc
{
  "approval": {
    "request_id": "ar_abc123",
    "state": "queued",
    "approver_hint": "an authorized admin on this team",
    "approval_url": "https://app.posthog.com/agents/<slug>/approvals/ar_abc123",
  },
}
```

`approval` present + `state: "queued"` → it did **not** write yet.

### What to tell the user

One line, with the link — this is the "place they can make the
approved change":

> Drafted a runbook update for `ingestion-500s` (added kafka-lag as a
> confirmed cause). Queued for review — approve it here:
> https://app.posthog.com/agents/sre-slack-bot/approvals/ar_abc123.
> It lands in memory once approved.

Rules:

- **Never say "saved" / "updated the runbook" before the approval
  lands.** It hasn't. Say "drafted" / "queued".
- Don't paste the raw envelope or speculate about who approves.
- Don't re-propose the same change in a loop — the platform dedupes
  and it just confuses the reader.
- Finish your turn. The session stays live; a wake message resumes it
  when the decision lands.

### When the decision arrives

A later `user` message carries the outcome — read `state`:

- `approved` — it's in memory now (the approver may have **edited** the
  content; the `result` reflects what actually landed). Confirm briefly,
  and reference the file going forward.
- `rejected` — surface the `reason`; ask if they want a revised draft.
- `expired` — TTL (7 days) elapsed; ask if it's still worth capturing
  and re-propose if so.

---

## The shape of getting better

Over weeks this corpus is the difference between an agent that
re-investigates every alert from scratch and one that opens with
"this is the third time `ingestion-500s` has fired; last two were
kafka consumer lag, here's the check and the fix." Curate it like
you'd want the next on-call to find it at 3am.
