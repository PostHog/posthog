# Request for comments: Agent experience analytics

## Background

Browser agents increasingly use websites in the same way people do.
When an agent cannot complete a task through an API or MCP tool, it can open a browser, sign in, navigate the product, fill out forms, and click through the interface.

PostHog currently gives customers no clear way to understand this traffic.
An interactive agent usually appears as an ordinary browser session, so it is mixed into human pageviews, funnels, and recordings.
Existing bot detection mostly identifies declared crawlers and automated user agents.
It does not identify a tool controlling a normal Chrome session on behalf of a user.

This creates a new set of product questions:

- Are browser agents using my website or product?
- How much of my traffic is agent-driven?
- What are agents trying to accomplish?
- Which pages and flows work well for them?
- Where do they repeatedly click, backtrack, encounter errors, or abandon a task?
- Do agents convert differently from people?
- Can I inspect examples and improve my product for both agents and humans?

The opportunity is to build **agent experience analytics**: an opinionated view of how interactive browser agents experience a customer's website.

The product should feel similar to the role Heatmaps plays for human behavior.
Heatmaps turns low-level interaction signals into an aggregate view of where people engage or struggle, then lets users inspect individual sessions behind a hotspot.
Agent experience analytics would turn behavioral signals into an aggregate view of where agents appear, what they do, and where they struggle, with individual sessions available as evidence.

### Why PostHog can build this

PostHog already has most of the relevant product primitives:

- **Web Analytics** understands sessions, pages, paths, conversion goals, entry and exit behavior, attribution, and frustration metrics.
- **Session Replay** captures the highest-fidelity sequence of pointer movement, clicks, typing, scrolling, navigation, errors, network activity, and DOM changes.
- **Heatmaps** aggregate privacy-preserving interaction data by page and can link hotspots to example sessions.
- **Product Analytics** can compare behavior through arbitrary trends, funnels, cohorts, and retention queries.

Replay ingestion also already calculates aggregate behavioral features such as pointer distance and velocity, direction changes, inter-action timing, scroll reversals, repeated targets, dead clicks, rage clicks, navigation, and errors.
That makes it possible to test whether likely agent sessions can be identified without introducing a separate customer-facing SDK.

### The hard part is detection

The main risk is not building another dashboard.
It is determining whether PostHog can identify a useful subset of interactive agent sessions with sufficiently few human false positives.

A click without preceding pointer movement is an interesting signal, but it is not proof of agent use.
Keyboard navigation, touch input, accessibility tools, stationary cursors, remote desktops, automated tests, and missing replay data can produce similar behavior.
Agents can also change over time or synthesize human-looking movement.

Interaction timing may be another useful signal.
The intervals between clicks, pointer movement, typing, scrolling, and page responses may differ in regularity, burstiness, or entropy between people and browser agents.
The useful direction is not obvious in advance: an agent may be more mechanically regular, or its model and environment may introduce more variable delays than a person.
This should be measured across tools and tasks rather than encoded as an assumption.

There is also a difference between classifying a complete session and deciding who controls the browser at a particular moment.
A session may contain long idle periods, human intervention, an agent handoff, or a mix of interaction modes.
The first product can reasonably classify a session as a whole, but it should not imply that every action in that session was performed by an agent.

The goal should therefore not be to identify every agent.
The initial goal should be:

> Identify a meaningful subset of interactive agent sessions with high precision, leave ambiguous sessions unknown, and help users understand the resulting behavior.

This must remain an analytics classification, not an identity claim or security control.

### Existing product boundaries are already mixed

The appropriate product boundary is not obvious from the current codebase.

Heatmaps appears in the Behavior category alongside Session Replay, while much of its backend now lives under Web Analytics.
Web Analytics already includes embedded recordings, frustrating-page analysis, and a separate bot-traffic tab.
Session-level analytics can already distinguish sessions that have replay data.

This suggests that collection, classification, discovery, and evidence viewing do not need to live in the same product surface.
The customer-facing experience should determine the boundary rather than the location of the first useful telemetry.

## Proposal

Build an experimental **Agent experience analytics** capability in PostHog.

The product promise is:

> See where browser agents use your website, understand where they succeed or struggle, and inspect the sessions behind those patterns.

### What the product should feel like

The primary experience should be an opinionated report, likely within Web Analytics, rather than only a new Session Replay filter.

A customer should be able to open an **Agents** view and answer:

- How many likely agent sessions did I have?
- Which pages and paths did they use?
- Where did they enter and leave?
- Did they complete my conversion goal?
- Which pages generated repeated clicks, errors, retries, or abandonment?
- How does agent behavior compare with human behavior?
- Which representative sessions should I watch?

An initial view could include:

- Likely agent sessions over time
- Detection coverage and unknown-session rate
- Top entry, exit, and visited pages
- Agent conversion rate compared with other supported sessions
- Pages with agent-specific frustration
- Errors, dead clicks, repeated interactions, and quick backs
- Representative sessions linked to the relevant page or pattern

This should be a product with an opinion about useful agent metrics.
A session property alone would leave users to discover the capability and assemble the relevant dashboards themselves.

### Classification contract

PostHog should produce a versioned, session-level result with enough information to support multiple product surfaces.
This initial contract describes the session overall rather than making a claim about who controlled the browser at every point in time.
A future time-window classification could support mixed human-agent sessions if experiments show it is reliable and useful.

The conceptual output is:

```text
classification: likely_agent | unknown | likely_human | unsupported
score: 0.0 to 1.0
model_version: string
support_status: string
reason_codes: string[]
```

The exact classes exposed in the first UI remain open.
In particular, it may be safer to launch with only `likely_agent` and `unknown` rather than presenting `likely_human` as a strong claim.

The classification should follow these principles:

- Optimize the `likely_agent` result for precision rather than recall.
- Use `unknown` whenever the evidence is ambiguous or insufficient.
- Use `unsupported` when the input modality or available telemetry cannot be evaluated responsibly.
- Never claim to identify Codex, Claude, or another specific provider from behavioral signals alone.
- Never automatically exclude these sessions from analytics.
- Never present the result as fraud, abuse, or security evidence.
- Keep the model and thresholds versioned so behavior can be reevaluated as agents change.

### Sensing, classification, and evidence are separate concerns

The proposal intentionally separates three layers:

1. **Sensing:** collect enough privacy-preserving behavioral information to evaluate the session.
2. **Classification:** produce a shared, versioned session-level result.
3. **Product experience:** aggregate the result into useful reports and let users inspect supporting evidence.

The likely starting point for sensing is Session Replay because it already contains the richest interaction sequence and an existing feature-extraction pipeline.
That does not mean Agent experience analytics must be presented as a Replay feature.

The classification should become shared session data that can be used by:

- Web Analytics for discovery and aggregate reporting
- Session Replay for individual-session inspection
- Heatmaps for spatial comparisons
- Product Analytics for custom breakdowns and funnels

This keeps the first implementation practical without making the long-term product depend on a particular navigation location.

### Evidence placement

Every aggregate claim should lead to evidence.

Depending on the question, the best evidence may be:

- A recording showing the complete session
- A page-level interaction summary
- A heatmap comparing likely agent and other interactions
- A sequence of captured events and errors

Session Replay is the obvious initial evidence viewer because the same telemetry may power the classification and the recording lets users judge the result themselves.
However, the product should link into Replay rather than requiring users to begin their investigation there.

Heatmaps could later support an agent comparison mode:

- All supported sessions
- Likely agent sessions
- Other supported sessions
- Side-by-side agent and human click patterns
- Agent-only dead-click or repeated-click hotspots

This would make the Heatmaps analogy tangible while preserving a broader Web Analytics entry point.

### Detection feasibility before broad implementation

Before committing to a large product build, PostHog should run a focused feasibility study using PostHog's own capture and analysis code.

A standalone experiment playground can run controlled tasks, but PostHog should not import its packages, feature definitions, types, fixtures, or model artifacts.
Any useful ideas must be independently implemented against PostHog's telemetry and architecture.

The study should include:

- Real browser agents using different tools and interaction strategies
- Controlled humans using mouse, trackpad, keyboard, touch, and accessibility tools
- Successful, failed, abandoned, and recovered tasks
- Different browsers, viewports, network conditions, and page behaviors
- Complete holdouts by agent configuration and human participant
- Evaluation of existing replay-derived features before adding browser capture

The study should answer:

- Is there a high-precision region that identifies useful agent traffic?
- Which behavioral signals generalize across agent tools and tasks?
- Do inter-action timing distributions, cadence, burstiness, or entropy generalize across tools and tasks?
- Which human input modes create false positives?
- How often is existing telemetry sufficient to classify a session?
- Can short rolling windows be classified reliably, or is a complete session required?
- What additional content-free signals, if any, materially improve performance?
- Does the resulting classification enable useful aggregate product insights?

If high-precision classification is not feasible, PostHog should not ship a misleading agent detector.
The same work may still support a narrower product around automation-like behavior, unusual interaction patterns, or agent friction without asserting who controlled the browser.

### Initial scope

The first customer-facing version should focus on web sessions with enough supported behavioral telemetry.

It should include:

- A high-precision likely-agent classification
- Coverage and uncertainty reporting
- An aggregate Agent experience view
- Page, path, conversion, and frustration analysis
- Links to representative recordings
- A Replay filter for likely agent sessions
- Clear experimental and methodological copy

It should not initially include:

- Exact agent-provider identification
- Security, fraud, or abuse enforcement
- Automatic bot or agent exclusion
- Interface adaptation while a session is active
- Native mobile classification
- A second standalone browser SDK
- Customer production sessions as unconsented training data
- LLM-generated recommendations

### Relationship to explicit identification

Behavioral detection and explicit identification are complementary.

PostHog could later let instrumented agents declare properties such as an automation provider, tool, or run identifier.
Explicit identification would be more reliable for cooperative agents, while behavioral classification would cover uninstrumented sessions.

Explicit metadata must not become a prerequisite for the initial product promise, which is to reveal agent traffic customers do not already know how to measure.

### What success looks like

This RFC is successful if it establishes agreement on the product opportunity and the next learning step, not if it precommits every implementation detail.

Evidence for moving forward would include:

- A controlled study finds a useful, high-precision likely-agent region.
- Human false positives are acceptably low across evaluated input modes.
- A meaningful portion of agent sessions has sufficient telemetry.
- Reviewers agree that the aggregate report answers a real customer question.
- Example sessions reveal actionable differences in conversion or friction.
- The classification can be explained honestly without implying certainty.

## Alternatives considered

### Make this primarily a Session Replay feature

The simplest implementation path is to add an agent score, filter, and badge to Replay.

Replay is likely the best initial sensing pipeline and evidence viewer, but it is not the clearest primary product experience.
A recording list answers "which sessions should I watch?" but does not naturally answer "how much agent traffic do I have, where does it go, and where does it fail?"

Replay should remain part of the proposal, but as evidence and investigation rather than the complete product.

### Make this primarily a Heatmaps feature

The original observation concerns cursor movement and clicks, and the product analogy to Heatmaps is useful.

However, current heatmap data is optimized for spatial aggregation by page.
It does not contain the complete movement, timing, navigation, typing, and error sequence needed for robust session classification.
Heatmaps also provides only one view of agent behavior and does not naturally cover conversion, paths, or abandonment.

Heatmaps is a strong future comparison and evidence surface, but too narrow to be the complete product.

### Add interactive agents to the existing Bots tab

Web Analytics already has a Bots tab based primarily on user-agent and IP classification.

Declared crawlers and interactive browser agents are different phenomena:

- Crawlers often do not execute JavaScript or create normal sessions.
- Interactive agents may use ordinary Chrome, execute JavaScript, and behave like users.
- A known AI crawler is not necessarily completing tasks through a user interface.
- An interactive browser agent may not declare itself at all.

Combining them immediately would make both datasets harder to understand.
They could eventually sit under a broader automated-traffic concept, but should retain separate detection methods and metrics.

### Expose only a session property in Product Analytics

A shared session property is useful for advanced users and should probably exist eventually.

It is not enough as the primary product.
Customers would need to know the property exists, understand the model, and build their own trends, funnels, and friction analysis.
That misses the opportunity to define what good agent experience analytics should look like.

### Build a separate top-level Agent analytics product

A dedicated product could eventually be justified if agent traffic becomes a major category with its own workflows.

That is premature before detection feasibility and customer demand are validated.
Starting within Web Analytics makes the concept discoverable next to existing traffic, page, and conversion analysis while keeping the option to separate it later.

### Ship a separate browser detector SDK

A purpose-built SDK could capture exact geometry and run a classifier in real time.

It would also require customers to install and configure another system, expose model logic to the browser, and duplicate behavior already captured by PostHog.
It would weaken the automagic product promise and prevent historical classification.

PostHog should first test what is possible with existing capture.
Additional content-free browser signals should be added only when experiments show they materially improve detection.

### Rely on user-agent, headless-browser, or automation flags

These signals are inexpensive and useful as weak evidence.

They are insufficient for the core opportunity because modern computer-use agents may control a normal browser with an ordinary user agent.
They also overfit to current implementations and are easy to remove or spoof.

### Require agents to identify themselves

An explicit agent identifier would provide strong ground truth and should be supported for cooperative integrations.

It does not solve the discovery problem.
Customers are specifically interested in agent traffic they did not instrument or know was present.

## Open questions

### Product shape and ownership

- Is Web Analytics the right primary home, or should this become a separate Behavior or Agent analytics product?
- Should the initial experience be a dedicated Agents tab, an opinionated dashboard, a page report mode, or something else?
- Should interactive agents and declared bots eventually share an automated-traffic area, or remain separate permanently?
- Which team should own the cross-product experience and the ongoing quality of the classification?

### Sensing

- Is Session Replay the right long-term sensing mechanism, or only the fastest path to testing the idea?
- Can the product provide useful coverage for customers who have Web Analytics enabled but Session Replay disabled?
- Would a lightweight, heatmap-like behavioral capture mode provide enough signal with lower cost and a clearer privacy boundary?
- Which signals are already available consistently across Cloud regions and self-hosted deployments?
- Which additional browser signals materially improve held-out performance enough to justify capture changes?
- How should replay sampling, dropped blocks, privacy settings, and partial sessions affect support status?

### Evidence viewing

- Is a full recording always the most useful evidence, or should page-level interaction summaries be the default?
- Should users be able to compare agent and human behavior directly in Heatmaps?
- How should aggregate reports select representative sessions without presenting cherry-picked examples?
- Can users inspect the reason for a classification without turning weak correlations into misleading causal explanations?

### Detection quality

- What precision and false-positive rate are required before exposing `likely_agent`?
- Should the first product expose `likely_human`, or only `likely_agent`, `unknown`, and `unsupported`?
- Which human input modes must be covered before alpha, especially keyboard and accessibility use?
- How should automated tests and synthetic monitoring be classified?
- How should the model handle agents that synthesize realistic pointer movement?
- Are agents consistently more or less temporally regular than people, or is timing useful only in combination with other signals?
- Should the product classify only complete sessions, or identify likely agent-controlled intervals within a mixed session?
- How often must models be reevaluated as agent tools and browser-control strategies change?

### Customer value

- Which questions are most valuable: traffic volume, conversion, discoverability, friction, task completion, or recordings?
- Is page-level friction enough without knowing the task the agent intended to complete?
- Should customers define a conversion goal for the Agents view, or should PostHog infer useful success signals?
- Do customers want to improve experiences for agents, exclude them from reporting, or both?
- What feedback or correction mechanism would customers trust and use?

### Privacy and communication

- Does using replay-derived features for classification require separate enablement or updated product copy?
- Which derived features and score explanations are appropriate to expose?
- How should PostHog communicate that this is probabilistic analytics rather than proof of identity?
- Should classification feedback ever be used for training, and what explicit consent would that require?

### Rollout decision

- What result from the controlled feasibility study is strong enough to justify building the first customer-facing experience?
- If reliable identity classification is not feasible, is a product around automation-like behavior still valuable?
