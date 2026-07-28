# RFC: Connecting Scouts, Loops, and Workflows

## Background

Scouts, Loops, and Workflows are three ways to automate work in PostHog, but their boundaries are becoming difficult to infer from the products themselves. People are asking [what the difference is between Scouts and Loops](https://posthog.slack.com/archives/C09SK2PAGKF/p1784801478526039) and [whether Workflows should power the self-driving tools](https://posthog.slack.com/archives/C0351B1DMUY/p1785152844973859).

For more context, the [PostHog Autonomy RFC](https://github.com/PostHog/requests-for-comments-internal/pull/1141) explains the original conception of Scouts, while the [Loops design document](https://github.com/PostHog/posthog/blob/c0db7aaf2a8b99423e25432a07f0391ee24bd5d9/products/tasks/docs/LOOPS.md) covers the motivation and implementation behind Loops.

Today:

- A Scout watches an area of a customer's product and decides whether anything deserves attention. Scout investigations execute as `TaskRun`s and produce findings, reports, analyses, canvases, or other artifacts.
- A qualifying Scout report may indirectly start implementation through the team-level autostart policy. That implementation is a separate `TaskRun`; the Scout does not perform it or invoke a Loop.
- A Loop repeatedly delegates a saved job to an agent. For example, its saved job might be "review each newly opened GitHub issue, reproduce the problem, and propose a fix." A schedule, API request, GitHub event, or manual action fires it. Each accepted fire creates a `LoopFire`, `Task`, and `TaskRun`.
- A Workflow executes predefined control flow through CDP and Cyclotron, a different runtime from Tasks. It supports actions, branches, delays, and waits, making it useful for durable processes such as "when a customer submits a negative survey response, notify their account owner, wait two days, and follow up if nobody responds." Workflows do not currently use `TaskRun`s or execute sandboxed agents.

A `Task` is one durable unit of agent work. It can be started directly, created by a Scout or Loop, or eventually called by a Workflow. Tasks and TaskRuns provide shared agent execution rather than another automation model.

These systems are beginning to connect. The [long-running Workflow steps RFC](https://github.com/PostHog/requests-for-comments-internal/pull/1204) proposes allowing a Workflow to wait while a Task or agent runs elsewhere. In the other direction, Scouts may monitor Workflow results and start work when something goes wrong.

One motivating application is an "AI SRE." PostHog already has much of the context needed to investigate incidents: error tracking, logs, traces, session replay, product analytics, and deploy information.

A near-term version could be an opinionated Scout that also accesses Grafana, Kubernetes, incident history, Slack, and GitHub through MCP. It watches for problems, correlates the available evidence, and produces a diagnosis in Inbox. Initially, a person decides what action to take; we can automate more of the response as those actions become better understood and safer.

This could make us competitive with the AI investigation offered by a [$75k/year SaaS product](https://posthog.slack.com/archives/C09KTRWD3HD/p1784885869162899), although replacing its broader incident-management product would also require on-call schedules, escalation, and incident lifecycle management.

The example exposes the ambiguity this RFC needs to resolve. A scheduled Loop could inspect the same systems as the Scout. A known alert could trigger a repeatable investigation job. A Workflow could coordinate notifications, approvals, and escalation. Secure MCP connections are required regardless of which product starts the work.

The boundary therefore cannot be based on tools, schedules, or technical capability. It has to follow user intent: which product watches and decides what matters, which repeats a defined job, which coordinates known steps, and how work moves between them.

## Proposal

Concretely, this proposal adds three ways for these products to compose:

- A Scout artifact can visibly start a Task or fire an existing Loop.
- A Workflow can start a Task, wait for it, and resume with its result.
- TaskRuns use MCP for external tools and can invoke other durable agents through MCP.

### 1. Adopt explicit product boundaries

| Product | User defines | Product owns |
|---|---|---|
| Scout | An area to watch | Monitoring context, deciding what is significant, and surfaced artifacts |
| Loop | A repeated agent job and trigger | Delegation, trigger policy, and run history |
| Workflow | A trigger and predefined steps | Deterministic control flow, waits, and actions |

These are UX boundaries based on user intent, not exclusive technical capabilities.

Scouts and Loops can run on schedules, access the same tools, and produce similar results. A Loop can even perform Scout-shaped work. The distinction is that a Scout decides whether anything is worth surfacing, while a Loop performs a job the user has already decided should happen when it fires.

Tasks are intentionally absent from the table. A Task is the shared unit of agent execution and the direct UX for one-off work, not another automation model. Scout investigations execute as Tasks, and every Loop fire creates one.

Scout artifacts do not need follow-up work to be valuable. When action is needed, one-off work becomes a Task; work the user wants to save and repeat belongs to a Loop.

Workflows own predefined coordination rather than agent execution. They may start or wait for Tasks without absorbing the Tasks runtime.

Each product retains the lifecycle rules supporting that intent. Scouts own the context accumulated about an area and how findings are surfaced. Loops own triggers, overlap rules, failure handling, and run history. Workflows own their graphs, waits, actions, and publication lifecycle.

### 2. Make handoffs from Scout artifacts explicit

Scout artifacts should lead naturally to whatever happens next. From Inbox, a person should be able to:

1. Review or dismiss the artifact.
2. Start a one-off Task using it as context.
3. Send it to an existing Loop whose saved job covers the work.

Starting a Task should create a separate TaskRun containing the Scout's findings. Inbox should link the artifact to that run and show its status and result. The existing autostart policy should appear as the automated version of the same flow.

For example, a warehouse Scout might report that an incremental sync repeatedly fails on the same schema. If the team has a "diagnose and repair failed warehouse syncs" Loop, a person can send the report to it. The report becomes input to a new Loop run, and Inbox links the original report to the diagnosis or change it produces.

Sending an artifact to a Loop should use the existing `fire_loop` path. The Loop continues to own access checks, duplicate protection, limits, overlap, cancellation, and failure handling.

In both cases, the TaskRun should retain the input it received when it started, even if the source artifact later changes or is deleted.

Scouts should not create Loops automatically. We should first learn whether users want recurring work or need a faster route to one-off action.

### 3. Keep agent execution out of the Workflow runtime

When a Workflow needs agent work, it should start a Task through a dedicated Workflow action. The Task runs in the Tasks runtime with its own tools, credentials, sandbox, and lifecycle. The Workflow retains a reference to the TaskRun, waits if necessary, and resumes with its result.

For example, a Workflow could receive a support escalation, start a Task to investigate the customer's recent errors and sessions, and park. When the Task returns a diagnosis, the Workflow branches on the result and sends the appropriate response.

The [long-running Workflow steps RFC](https://github.com/PostHog/requests-for-comments-internal/pull/1204) proposes the park-and-resume mechanism needed for this. This RFC decides the ownership boundary: Workflows coordinate agent work, while Tasks execute it. We should not add sandboxes, repository access, or agent sessions to Workflow workers.

Agent-first authoring does not change that boundary. In the [Workflow canvas prototype](https://github.com/PostHog/code/pull/3535), an agent builds and tests a graph before a person publishes it. Once published, the Workflow still executes predefined steps.

A Loop may similarly display its agent-generated plan as a graph. Making that graph editable or publishable would turn it into authored control flow and requires a separate product decision.

### 4. Standardize agent-facing capabilities on MCP

The same external capability should look the same to an agent regardless of which product started its TaskRun.

For example, both a Scout looking for production regressions and a Loop investigating a known alert may need Grafana. Both should use the same Grafana MCP tools rather than separate Scout and Loop integrations.

A TaskRun should receive only the MCP servers, tools, and credentials explicitly authorized for that run. If a Workflow starts an investigation Task, it passes the alert and other context, not the Workflow's Grafana credentials.

This applies to tools used by agents during Task execution. Workflows may continue using their existing integrations for predefined actions such as sending a Slack message. MCP is not a replacement for every product integration.

MCP should also let one durable agent delegate to another. For example:

1. An investigation TaskRun identifies a likely code defect.
2. It calls a code agent exposed through MCP, passing its diagnosis and evidence.
3. The call starts a separate TaskRun and returns either its result or a reference to the run.
4. The code TaskRun resolves its own GitHub access and produces a PR.
5. PostHog links the investigation, code TaskRun, and PR so the user can follow the delegation.

This RFC therefore makes two decisions:

- MCP is the common agent-facing interface for external tools.
- Calling a durable agent through MCP creates an inspectable Task handoff.

It does not decide where connections are stored, how agent identities and approvals are implemented, or where policy and audit history live. The open [MCP gateway RFC](https://github.com/PostHog/requests-for-comments-internal/pull/1200) explores one possible implementation of those concerns.

Collaboration between sub-agents inside a single TaskRun remains out of scope. Shared context, concurrent side effects, cancellation, and coordination within one run require a separate RFC.

## Alternatives considered

### Limit Scouts to findings and PRs

This would treat PRs as the only meaningful Scout result. Reports, analyses, recommendations, and canvases are also useful outcomes.

### Turn every Scout action into a Loop

This would force one-off work into a product intended for saved repeated jobs. A Task is the better fit when work only needs to happen once.

### Run Loops inside Workflows

This would add sandboxes, repositories, credentials, and agent sessions to CDP workers. A Workflow can start or wait for a Task without executing it itself.

## Open questions

- Should report-to-Loop initially require a user action, or may teams configure a visible automatic rule?
- What Scout artifact content must be retained so the resulting TaskRun can act without repeating the investigation?
- What usage evidence would justify allowing Scouts to suggest new Loops after the initial handoffs ship?
