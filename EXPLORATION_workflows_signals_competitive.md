# Competitive exploration: can PostHog replace Polymorph / Pulsent?

## What these companies do

### Polymorph (YC W26) — usepolymorph.com

**Positioning:** "Personalization infra that improves retention, LTV, and CAC" for consumer and self-serve apps.

**Team:** David Nie (ex-Meta SMB Ads, $400M revenue impact, 200+ experiments), Manas Purohit (Gusto, Nira), Andrew Sy (Scale AI ML infra, 10M+ calls/day). Founded 2026, SF, 3 people.

**What it actually does:**

- Ingests data from analytics (PostHog, Amplitude), CRMs (HubSpot), data warehouses (Snowflake, ClickHouse), and support tools
- Builds "living user profiles" from behavioral signals — not static segments, continuously updated models of each user
- AI detects user intent signals (buying signals, churn risk, confusion patterns)
- Proposes targeting strategies based on real behavior — then automatically A/B tests them
- Triggers personalized actions (notifications, emails, in-app messages) at the right time/channel
- Auto-promotes what converts, pauses what doesn't — closed-loop optimization
- Claims 3.5M users across customers, some seeing 3.6x conversion lift

**Key differentiators vs. basic CDP:**

1. AI-driven signal detection (not manual rule setup)
2. Automatic experiment loop (propose → test → promote/kill)
3. Per-user personalization at scale (not segment-level)
4. Connects to existing stack rather than replacing it

### Pulsent — pulsent.ai

**Much less public information available.** Likely pre-launch or very early. No ProductHunt listing, no meaningful web presence found. The founders may have a prior product called "Swish." Appears to be focused on similar territory — session replay analysis driving personalized outreach — but without enough public detail to map specific features.

### Also notable: Human Behavior (YC X25) — humanbehavior.co

$5M from YC + General Catalyst. "AI that watches actual customers using your product through session replays to help you understand why they stay, convert, or leave." More analytics-focused but overlapping territory. Appears to include AI-identified user outreach (win-back, support, expansion emails).

### Also notable: Lucent (YC W26) — lucenthq.com

"AI that watches session replays to detect bugs and UX issues." Overlaps with PostHog's existing session problem signals but focuses on engineering/QA rather than customer outreach.

---

## Feature-by-feature: what PostHog has today

### 1. Session replay AI analysis — STRONG

PostHog already detects per-session problems via video-based LLM analysis:

| Problem type             | Description                                 |
| ------------------------ | ------------------------------------------- |
| `blocking_exception`     | Errors that stopped user progress           |
| `non_blocking_exception` | Errors user could continue through          |
| `confusion`              | Backtracking, hesitation, visible confusion |
| `abandonment`            | User abandoned a flow                       |
| `failure`                | General unsuccessful segment                |

Additional session-level AI outputs:

- **Frustration score** (0.0–1.0)
- **Outcome classification**: successful, friction, frustrated, blocked
- **Sentiment signals**: rage_click, repeated_error, backtracking, long_pause, abandonment, dead_click, confusion_loop, error_cascade (each with intensity 0.0–1.0)
- **Session tags**: onboarding, error, frustration, idle, checkout, form_interaction, support, feature_exploration, etc.

**Verdict: PostHog's session analysis is more sophisticated than what Polymorph/Pulsent likely have.** They rely on ingesting PostHog's data — PostHog generates it.

### 2. User data / living profiles — PARTIAL

PostHog has:

- Person properties (mutable, set by events or API)
- Event history (full timeline)
- Cohort membership (dynamic, based on property/event filters)
- Group properties (company/account level)
- `distinct_id` resolution (person → device/session mapping)

What Polymorph adds:

- Unified cross-source profile (analytics + CRM + support + revenue)
- AI-derived behavioral state (not just raw properties, but inferred intent)
- Continuous model updates (not just latest property values)

**Gap:** PostHog doesn't do AI-derived user states. It has the raw data but doesn't synthesize "this user is showing buying signals" or "this user is at churn risk" as a first-class computed property. This is Polymorph's core differentiator.

### 3. Triggers / signal detection — PARTIAL

PostHog has:

- **Event triggers**: workflow triggers on specific events with property filters
- **Batch triggers**: run queries on segments
- **Schedule triggers**: cron-based
- **Session problem signals**: AI-detected problems emitted to the signals pipeline

What Polymorph adds:

- AI-generated targeting strategies (not user-defined rules)
- Compound behavioral signals ("user viewed pricing 3x but didn't upgrade AND opened support ticket")
- Intent scoring (not binary trigger, but gradient)

**Gap:** PostHog triggers are rule-based. You define "when event X with property Y." Polymorph's pitch is "we'll tell you which signals matter and when to act." The AI strategy generation is the differentiator.

### 4. Actions / outreach — STRONG

PostHog has:

- **Email** (SES, with HTML templates, personalization via person properties and event data)
- **SMS** (Twilio)
- **Push notifications** (via OneSignal destination)
- **Slack** (native destination)
- **Webhooks** (generic HTTP)
- **48+ CDP destination templates** (Braze, Intercom, HubSpot, Klaviyo, Customer.io, etc.)
- **Workflow actions**: multi-step with delays, branching, conditions, conversion tracking

**Verdict: PostHog's action infrastructure is comprehensive.** More channels and destinations than what early-stage competitors likely offer.

### 5. Experimentation / optimization loop — STRONG (but not connected)

PostHog has:

- Feature flags (percentage rollouts, property-based targeting)
- A/B testing (experiments product with statistical significance)
- Conversion tracking in workflows (exit conditions)

What Polymorph adds:

- **Closed-loop optimization on outreach itself** — not just product experiments but "which message to which user at which time works best"
- Automatic promote/kill decisions

**Gap:** PostHog's experiments test product changes. Polymorph tests outreach strategies. PostHog _could_ do this (create experiment variants of a workflow) but it's not wired up.

### 6. Pre-built workflow templates — STRONG

PostHog has 19 workflow templates including several directly relevant to this use case:

| Template                                  | Relevance                                   |
| ----------------------------------------- | ------------------------------------------- |
| Re-engagement workflow for inactive users | Direct competitor to Polymorph reactivation |
| User stuck in onboarding alert            | Detects stuck users, alerts team            |
| Onboarding started but not completed      | Behavioral trigger → email sequence         |
| Notify sales for high intent users        | Intent signal → team notification           |
| Trial started → upgrade nudge             | Conversion journey                          |
| Heavy usage levels detected               | Behavioral signal → action                  |
| Negative survey response → alert team     | Feedback-driven outreach                    |

---

## What PostHog would need to build to replace these products

### Tier 1: Small wire, big impact (days of work)

**Emit session problems as person-level events**

Today, session problems only flow into the signals pipeline (for engineering triage). They never land on the person's event timeline. A ~20 line change in `a7b_emit_session_problem_signals.py` to also emit a `$session_problem` event via `posthoganalytics.capture()` with the person's `distinct_id` would make session problems triggerable by both workflows and destinations immediately.

This alone enables:

- "When user has a blocking_exception → wait 30 min → send empathetic email"
- "When user shows confusion in checkout → send support link"
- "When user abandons onboarding → re-engagement sequence"

**New workflow template: "Reach out after bad session"**

A pre-built template (template #20) that triggers on `$session_problem`, waits, checks if user returned, and sends a personalized email using the problem description. Instant demo-able value.

### Tier 2: Meaningful features (weeks of work)

**AI-generated email content from session context**

The session problem description (LLM-generated, e.g., "User tried to complete checkout but encountered a payment processing error after entering card details") could be fed into an LLM to generate personalized email copy. PostHog has the session analysis and the email sending — the missing piece is using one to populate the other.

This would require:

- Passing problem `description` as a workflow variable
- An LLM action node in workflows (or a Hog function that calls an LLM API)
- Email template with dynamic AI-generated content block

**Compound behavioral triggers**

Allow workflows to trigger on combinations of signals, not just single events:

- "User viewed pricing page 3+ times in 7 days AND has not upgraded"
- "User's frustration_score > 0.7 across last 3 sessions"

This could be done via batch triggers with HogQL queries, but a purpose-built "behavioral trigger" UI would be more accessible.

### Tier 3: Deep platform capability (months of work)

**AI-driven targeting / strategy suggestions**

This is Polymorph's core moat: "we'll tell you who to target and what to say." Building this means:

- Training models on what outreach strategies work across customers
- Suggesting workflow configurations based on product data
- Automatic A/B testing of outreach variants

This is a significant ML/product investment and probably not worth building until the basic wiring (Tier 1–2) proves demand.

**Living user profiles with computed behavioral state**

Synthesizing raw events into derived states ("churning", "power user", "buying intent") as first-class person properties. PostHog has all the data but doesn't do the synthesis automatically.

---

## Summary: coverage map

| Capability               | Polymorph                   | Pulsent         | PostHog today                                 | PostHog + Tier 1  | PostHog + Tier 2     |
| ------------------------ | --------------------------- | --------------- | --------------------------------------------- | ----------------- | -------------------- |
| Session replay analysis  | Via PostHog/others          | Via integration | **Native, deep**                              | **Native, deep**  | **Native, deep**     |
| Problem/intent detection | AI-driven                   | Unknown         | AI-driven (signals)                           | + person events   | + compound triggers  |
| User profiles            | Unified, AI-enriched        | Unknown         | Properties + events                           | Same              | Same                 |
| Email/SMS/push           | Basic channels              | Email focus     | **18+ templates, SES, Twilio**                | Same              | + AI content         |
| Multi-step journeys      | Unknown                     | Unknown         | **Workflows (delays, branches, conversions)** | + session trigger | Same                 |
| 48+ integrations         | ~10 integrations            | Few             | **48+ destinations**                          | Same              | Same                 |
| A/B test outreach        | Auto-optimize               | Unknown         | Experiments (separate)                        | Same              | Workflow experiments |
| AI strategy suggestions  | **Core differentiator**     | Unknown         | None                                          | None              | Possible             |
| Setup time               | "Minutes" (data connectors) | Unknown         | Already integrated                            | Zero setup        | Zero setup           |

## The PostHog advantage

PostHog's unique position: **it owns both the observation layer (session replay + AI analysis) and the action layer (workflows + destinations + email)**. Polymorph and Pulsent are building the bridge between tools they don't own. PostHog doesn't need a bridge — it just needs to connect two rooms in its own house.

The Tier 1 changes (emit session problems as events + template) could be built in days and would cover the core "watch sessions → email users" use case that these companies are pitching. For a demo at AI Tinkerers on June 12, this is the most compelling path.
