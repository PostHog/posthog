# Conversations

Conversations is an AI-first support hub that ingests every customer exchange (site widget, Slack connect, email, custom channels) into one ticket stream, then measures how often the agent resolves threads autonomously versus when it escalates to a human teammate.

## Ticket workspace

- Unified inbox with status pills, quick filters, and per-ticket detail panes combining metadata, transcript, and human/AI handoff history.
- Live resolution stats that surface AI containment rate, fallback reasons, and trendlines for each source or queue.

## Knowledge + guidance rails

- Content library for curated articles or bespoke snippets, each scoped by audience traits (geo, plan, segment) and individually toggleable.
- Guidance controls for tone, policy reminders, and escalation rules so the AI knows when to defer; guidance packs can also be switched on/off to experiment safely.

## Playground + testing

- Sandbox that can load any content + guidance combination, simulate inbound queries, and preview AI answers with visibility into retrieval, reasoning, and escalation decisions before rolling changes to production.

## Scenes

- `/conversations` – ops landing page with KPIs (AI containment, escalation %, SLA breaches), urgent queues, and recent config changes.
  - KPI tiles with comparison deltas (AI containment rate, time-to-first-response, escalation %, SLA breach count)
  - Escalation firehose showing blocked items
  - Ticket pods (last 10 escalated, last 10 SLA breaches, last 10 awaiting reply) with “view all” jumping into `/conversations/tickets` prefiltered
  - Recent content/guidance edits with quick revert
- `/conversations/tickets` – unified ticket list with status/funnel filters and per-ticket KPIs.
  - Saved filter presets + search by customer/source
  - Bulk actions (assign, snooze, reopen)
  - AI vs human resolution badge per row
  - Filters: status (open/pending/resolved), source channel, SLA state, AI-only vs AI+human, assigned team/owner, priority, customer segment, created/updated time, escalation reason
- `/conversations/tickets/:id` – ticket detail surface with transcript, AI/human timeline, and action sidebar.
  - Threaded conversation with attribution (AI/human)
  - Context cards: customer profile, journey, SLAs, recent events, relevant session recording, historical tickets
  - Inline actions (reply, summarize, escalate)
- `/conversations/analytics` – resolution insights showing containment rate, escalation triggers, and channel drilldowns.
  - Containment trend charts by channel/queue
  - Escalation reason breakdown and alerting
  - Exportable leaderboard for agent + AI performance
  - Graphs: AI containment over time, escalations by reason/channel, SLA breach funnel, median time-to-first-response vs resolution time, ticket volume stacked by source, agent vs AI CSAT
- `/conversations/content` – library manager for articles/snippets with audience targeting toggles and version history.
  - Audience scoping (geo, plan, segment)
  - Draft/published states with approvals
  - On/off toggles + version diffing
- `/conversations/guidance` – tone + escalation rule composer including activation switches and preview notes.
  - Tone presets with guardrail rules
  - Escalation playbooks (rules + destinations)
  - Safe toggle + rollout scheduling
- `/conversations/playground` – testbed to run prompts against selected content/guidance stacks before deploying.
  - Scenario picker (channel, persona, language)
  - Retrieval + reasoning trace viewer
  - Feedback loop to update content/guidance directly
- `/conversations/settings` – configuration hub for channels and defaults.
  - Slack connect setup (OAuth, channel mapping, per-channel visibility toggles)
  - Widget controls (enable/disable, theme colors, greeting text, launcher behavior)
  - AI assistance toggles (global on/off, per-channel containment thresholds, fallback policies)
  - Default ownership/escalation rules per channel

## Ticket model

- Identity: ticket ID, channel/source metadata, timestamps for creation + latest activity.
- State: status (open/pending/resolved), priority, SLA clock, current owner/queue.
- Customer context: flexible container that can hold either a known person/company profile or anonymous traits (fingerprint, geo, device, recent events, session recording link).
- Conversation log: chronological chat with attribution (customer, AI, human teammate) plus attachments.
- AI metadata: containment flag, confidence, fallback reason, referenced content/guidance IDs.

### Conversation log specifics

- Participants: supports 1-to-many including customers, teammates, and AI bots with explicit attribution.
- Messages: threadable, rich-text, mention-aware, attachment-friendly.
- Attachment model: stored as reusable discussions so the same chat thread can embed under tickets, recordings, insights, etc.
- Storage: reuse the existing `Comment`/discussions model by scoping threads to ticket IDs (avoid building a new chat table unless the current model blocks threading or formatting needs).
- Visibility: add `is_private` (or `visibility` enum) plus an owner field to the discussion scope; private chats store an allowlist of participant IDs/bots so only they can post/view, while public chats inherit default permissions.

## Channels

- Custom widget: embeddable web messenger that runs on customers’ sites, pipes threads into tickets in real time, and supports AI autoresolution before escalating to humans.
- Slack connect: bidirectional sync between shared Slack channels and tickets—messages, files, and reactions mirror into the ticket chat while AI/human replies push back into Slack with attribution.
