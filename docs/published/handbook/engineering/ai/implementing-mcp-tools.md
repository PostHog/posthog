---
title: Implementing MCP tools
sidebar: Docs
showTitle: true
---

MCP tools are atomic capabilities – CRUD operations and simple actions that agents compose into workflows.
Every product should be accessible through the MCP server.
Tools answer "what can I do?" (list feature flags, execute SQL, create a survey).

For teaching agents _how_ to use these capabilities in combination,
see [Writing skills](/handbook/engineering/ai/writing-skills).

## TL;DR

```sh
# 1. Only for a product with no YAML yet: create one with no tools
pnpm --filter=@posthog/mcp run scaffold-yaml -- --product your_product \
    --output ../../products/your_product/mcp/tools.yaml

# 2. List the operations without a YAML entry, then add the ones agents need as enabled tools
pnpm --filter=@posthog/mcp run scaffold-yaml -- --candidates --product your_product
pnpm --filter=@posthog/mcp run scaffold-yaml -- --add your_product_things_list --product your_product

# 3. Configure the YAML – adjust titles and descriptions, add annotations for PATCH/POST/PUT
#    Place in products/<product>/mcp/*.yaml (preferred, e.g. actions, cohorts)

# 4. For read/list tools backed by PostHog database rows, add a HogQL system table
#    in posthog/hogql/database/schema/system.py and a model reference in
#    products/posthog_ai/skills/querying-posthog-data/references/

# 5. Generate handlers and schemas
hogli build:openapi

# 6. Refresh the tool input schema snapshots (CI unit tests fail on a stale snapshot)
pnpm --filter=@posthog/mcp exec vitest run tests/unit/tool-schema-snapshots.test.ts -u
# A tool behind a new `feature_flag` needs that flag in the test's `featureFlags` map, set to the value that shows the tool:
# true for a plain gate, the variant string for a variant gate, a non-true value for a `disable` gate.

# 7. Only when the YAML uses ui_apps: regenerate the UI apps (CI checks they are current)
pnpm --filter=@posthog/mcp run generate:ui-apps

# 8. Merge to master – CI builds and distributes automatically
```

## Tool design principles

MCP tools should be **basic capabilities** – atomic CRUD operations and simple actions.
Agents compose these primitives into higher-level workflows.

**Good tools**:

- List feature flags
- Get an experiment by ID
- Create a survey
- Summarize a session recording

**Bad tools**:

- "Search for session recordings of an experiment" – this bundles multiple concerns.
  Instead, expose four composable tools:
  list experiments, get experiment, search session recordings, summarize sessions.

The reasoning: agents are better at composing simple tools than navigating complex ones,
and simple tools are reusable across many workflows.

For lookup tools, return an explicit normal result when absence is an expected answer (for example,
checking whether an event's session has a recording). Keep invalid inputs, permission failures, and
server failures as tool errors so MCP Analytics measures genuine failures rather than routine misses.

Preserve API errors with `throw result.error` or `wrapError(message, result.error)` from `@/lib/errors`.
Copying only the message loses the HTTP status and retry guidance.
For HTTP 503 responses, the shared client passes a numeric `Retry-After` value to the agent as a minimum wait.
It does not retry these requests automatically.

## Project and organization context

Resolve tool targets through `context.stateManager.getProjectId()` or `getOrgID()`. The Hono server snapshots the active selection for each request and stores it per credential and MCP transport session. Separate sessions can use the same credential concurrently in different organizations and projects, with or without URL pins. Unpinned sessions initialize from the user's active selection within the credential's allowed scope; later website changes do not retarget an existing session. Organization switches clear the previous project, and project switches keep the organization consistent with the selected project.

The shared token cache holds credential and entity metadata. Its `orgId` and `projectId` selection keys remain only for requests without a session or conversation identity. Session-aware tools must use the state manager instead of reading those keys directly. Session selections expire after 24 hours without requests.

For sessionless clients, the server scopes selection to the SDK's echoed `conversation_id`, bound to the credential and separated from transport session IDs. The dispatcher restores echoed handles before state resolution. When the SDK mints a handle on the first tool call, the executor resolves state with that handle before running the tool. Switches require a carried session or conversation handle, including when called through `exec`. A switch without one returns an error and a new handle; the client must retry with that handle and echo it on subsequent calls. Calls without either identity start from the connection's pin or default selection. Clients unable to retain handles should pin the project or organization in the connection URL. The SDK remains responsible for generating and normalizing conversation handles and producing analytics.

Sessionless legacy batches resolve each call's handle and state independently before checking whether a switch is allowed. The wrapper's `sessionId` query parameter groups analytics but cannot restore selections; wrapper-only calls still receive SDK-minted conversation handles.

State managers share credential, user, and entity lookups within one HTTP request, including when a new conversation handle requires another resolution. Lookup keys include the credential cache scope and entity ID. Each call retains its own state manager, selection, flags, and API client. Redis TTLs still govern freshness, and rejected lookup promises are removed so later attempts can retry.

Remote flag evaluations share the same request-local cache when the credential, distinct ID, groups, and requested flag keys match. Flag values and payloads stay separate across different evaluation contexts. Request overrides are applied after the shared evaluation, and failed evaluations remain retryable.

Session defaults are saved once with `SET NX` and kept separate from explicit selections. Lazy organization and project resolution updates only the request snapshot, so a delayed read cannot replace a newer switch in the same session.

An org-only default does not freeze a failed project lookup. Project discovery retries within the saved organization and records the first successful result separately with `SET NX`. Organization-scoped discovery establishes project ownership without a second global metadata lookup. Organization switches can retain a selected project using the destination organization's team list when project metadata is unavailable.

## SQL-first data retrieval

The MCP server instructs the agent to read data through a unified HogQL interface
(list and get tools are generally excluded),
which unlocks flexibility in data retrieval, search, and manipulation.
Additionally, the consumer has access to a skill that provides schema references and example patterns,
giving it richer context about PostHog's data model.

Here, "SQL-first" describes entity retrieval, not a preference for every analytics task.
Choose typed queries or SQL from the required calculation and output, as described in [query selection guidance](./writing-skills.md#query-selection-guidance).

Primarily oriented toward coding agents (PostHog Desktop, PostHog AI, Claude Code).

### Knowledge source checks

When the MCP server advertises Business Knowledge or documentation search tools, its agent instructions require one search of each available source before the first answer to a request. Business Knowledge is searched first, followed by current PostHog documentation. If a search fails or returns no relevant result, the agent continues with the other available evidence. In exec sessions with skill discovery enabled, the agent loads the relevant skill before it runs these searches.

## Intent prompt trials

The MCP Analytics SDK adds a `context` argument asking the agent to explain why it calls a tool.
The `mcp-intent-prompt` flag can select a different description for ordinary external MCP requests.
Disabled flags, missing or invalid payloads, impersonation, and analytics-suppressed requests retain the SDK default.

Set the description directly in the flag payload:

```json
{
  "prompt": "The intent instruction, including its privacy constraints."
}
```

The server reads the text from the existing flag evaluation and accepts only nonblank text of at most 2,000 characters.
Keep the instruction abstract and preserve the default prompt's constraints against identifying or sensitive information.
Start with a release condition matching one authenticated user's distinct ID; do not add an unconditional release condition.

Clients cache tool schemas. Refresh the client's tool list or reconnect after deployment before collecting trial data.
Use the targeted user's calls after that refresh for offline evaluation, and record when the payload changes.
Existing intent analytics stay unchanged; the server does not capture the prompt text separately.

This collection trial changes no tool results and adds no recommendations or elicitation.
Evaluate intent against independently recorded abstract task goals, checking invented goals, identifying details, and appropriate uncertainty.

## Interview recruitment with URL elicitation

> [!CAUTION]
> **Unsolicited elicitation can spam users and damage trust in the MCP.**
> A native dialog interrupts the user's work even when it is easy to implement or feature-flag.
> This recruitment flow is a narrow exception, not a general-purpose advertising or survey channel.
> Read the [MCP agent policy](../../../../../services/mcp/AGENTS.md#unsolicited-elicitation-high-risk) before adding unsolicited prompts or expanding this flow.
> Reviewers should challenge the interruption's user value, audience, timing, frequency, opt-out behavior, and measurement.

The `mcp-interview-recruitment` multivariate flag selects one optional interview invitation before a tool call.
Each variant key identifies a campaign and has its own invitation payload.
To add an approved study, read [the integration guide](../../../../../services/mcp/INTERVIEW_RECRUITMENT.md).
Create the flag in the MCP server's analytics project and manage its audience and rollout there.
A missing or disabled flag skips recruitment. Local development also keeps it disabled unless a
development flag override explicitly enables it with an explicit `MCP_INTERVIEW_RECRUITMENT_PAYLOAD`.
See the [local testing instructions](../../../../../services/mcp/INTERVIEW_RECRUITMENT.md#code-and-checks).

Set each variant's JSON payload to customize its invitation without deploying:

```json
{
  "message": "Squeal on our MCP. Book a 20-minute chat. We'll pay you in PostHog merch.",
  "booking_url": "https://cal.com/adam-posthog/posthog-chat",
  "min_completed_tool_calls": 3,
  "min_session_age_seconds": 120
}
```

Each variant must explicitly supply `message` and `booking_url`; omitted timing fields use the defaults above.
A boolean `true` identifies the original `mcp-research` campaign, but requires the same explicit copy and URL.
A missing payload skips recruitment; no invitation copy or booking URL is supplied by the code.
A malformed payload, an empty message, a message over 1,000
characters, or a non-HTTPS booking URL skips recruitment. Flag values and payloads come from the same
evaluation, with the same audience properties. Payload edits apply to subsequent requests without
restarting the server. A displayed invitation keeps its original campaign, copy, and URL even if targeting changes.
Use release conditions to assign variants, with higher-priority conditions first. One evaluation selects
one campaign; no invitation queue is created for overlapping audiences.

Every release condition for every variant must include an AND condition excluding the [shared recruitment exclusion cohort](https://us.posthog.com/project/2/cohorts/641799) (`641799` in US project `2`).
Use `type: "cohort"`, `key: "id"`, `operator: "not_in"`, and `value: 641799` for this filter.
Release conditions are OR alternatives, so a separate exclusion-only condition does not protect other campaigns.
Maintain excluded users and organizations in the shared cohort, preserve this exclusion when editing the flag, and verify that excluded people receive no variant.

By default, an eligible conversation must complete three successful product tool calls and have been
observed for at least 120 seconds. The earliest invitation is before its fourth product call, once both
thresholds are met. Discovery commands, skills, documentation lookups, private scout tools, and failed calls do not count.
The timer starts at the first eligible product request; it does not measure when the chat UI opened.
The payload accepts 0–1,000 completed calls and 0–86,400 seconds. Setting both to zero permits an
immediate invitation for testing.

Progress is updated atomically in shared Redis, scoped to the user, instance, client, and conversation
handle already resolved by the MCP Analytics SDK. The SDK returns a handle on the first call for the
agent to echo on subsequent calls. If it is missing or changes, progress does not accumulate across
those calls. This measures calls observed under that handle, not chat messages or an independently
verified client UI conversation boundary. A client reusing a handle across chats also reuses its progress.
The counter expires after 24 hours without eligible activity, caps at 1,000 completions, and deduplicates
identical RPC IDs and tool arguments. A retried call with a new RPC ID is a new request. Continuations
of an invitation do not increment it.

Flag evaluation uses the authenticated user's distinct ID and the existing organization/project groups.
Use existing person or group properties and cohorts for additional audience filters. The server does
not inject client metadata as person-property overrides during flag evaluation.

No client-name or task conditions are required in the flag. The server requires native URL
elicitation support and enforces its surface and task exclusions independently of the flag.
Use the flag for rollout and any additional audience filters. Alternative condition groups are OR
conditions.

Only requests classified as `mcp` can recruit. Other surfaces, including PostHog AI and recognized
self-driving OAuth applications, always skip recruitment. Task-bound requests and credentials with
`internal_run:read` also skip recruitment even if their source is `mcp` and the flag is enabled.
Client names and consumer headers are self-reported; they do not prove a human is present.
A third-party unattended agent using the same identity and capabilities as an interactive client
cannot be distinguished by this feature.

The invitation uses native URL elicitation for clients advertising URL support. Clients with only
form support continue without an invitation. No MCP App, extra tool, or agent instruction is involved.
The client displays the booking URL and asks permission to open it, using its own controls and labels.
No questionnaire is displayed.

Protocol revision `2026-07-28` uses an `input_required` result. The original tool runs after the client
returns the invitation response, without waiting for a booking. Earlier protocol connections remember
URL support from initialization and receive an `elicitation/create` request alongside the completed
tool result in a short SSE response. These clients must accept `text/event-stream`; JSON-only requests
and batches skip recruitment. The tool completes once, without waiting for the invitation reply.
Both paths include an `elicitationId` for clients that require it when parsing URL requests.
Sessions initialized before capability persistence was deployed need to reconnect before they can recruit.

Claude Code can keep its dialog open after opening the URL until the user chooses “I'm done.”
The server cannot remove that client-controlled step. The `2026-07-28` protocol has no URL-elicitation
completion notification; see the [SDK protocol notes](https://ts.sdk.modelcontextprotocol.io/v2/servers/elicitation).

- Accepting the link records `booking_link_accepted` and stops further invitations. This records
  permission to open the booking page, not a completed booking or permission to contact an account email.
- Declining the invitation records `do_not_ask_again` and stops further invitations.
- Canceling or abandoning the invitation starts a seven-day cooldown.

Responses are JSON records in the MCP server's shared Redis, under
`mcp:interview:{<identity hash>}:response`. The identity hash is the SHA-256 hex digest of
`JSON.stringify([publicPostHogBaseUrl, distinctId])`; it scopes the preference to the authenticated
user and PostHog instance, across tokens, sessions, and projects. Submitted records contain
`distinct_id`, `campaign_id`, `response`, and `responded_at`. Suppression is shared across campaigns. Use `SCAN MATCH 'mcp:interview:*:response'` and `GET`
to inspect responses. This implementation records the invitation response; it does not send an email or track completed bookings.

Accepted-link and opted-out records have no TTL. They remain suppressed until reset, provided Redis
retains the records; this is not a separate durable database. Do not put these keys behind an
expiring cache or delete them during cache maintenance. Cooldown records expire after seven days.
Already-suppressed users skip progress writes and booking-link creation; the final reservation remains atomic.
Redis failures skip new invitations. On `2026-07-28`, a response write must succeed before the
original tool runs; the client can retry the continuation if that write fails. Earlier protocols
already completed the tool, so an invitation reply only updates suppression and never reruns it.

Recruitment analytics use the existing PostHog SDK and the MCP server's analytics project:

| Event                                | Meaning                                                                                                               |
| ------------------------------------ | --------------------------------------------------------------------------------------------------------------------- |
| `mcp interview invitation sent`      | The server returns a native invitation after reserving it. This does not confirm that the client rendered the dialog. |
| `mcp interview booking link opened`  | The invitation's redirect URL receives its first GET request. Repeated opens do not add events.                       |
| `mcp interview invitation responded` | A valid response is saved, with `response` equal to `accept`, `decline`, or `cancel`.                                 |

Tool-call events also carry recruitment diagnostics through the existing SDK capture path, without
an extra event per eligibility check:

| Property                                                                             | Meaning                                                                                                                                                                |
| ------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `interview_recruitment_reason`                                                       | The first gate that skipped recruitment, `eligible` for a legacy call ready before execution, or `continuation` when resuming an invitation.                           |
| `interview_recruitment_url_supported`, `interview_recruitment_form_supported`        | Whether this request explicitly advertises each elicitation mode. `null` means the request carries no capability metadata; it does not prove the client lacks support. |
| `interview_recruitment_campaign_id`                                                  | Selected campaign, when a valid recruitment configuration exists.                                                                                                      |
| `interview_recruitment_completed_calls`, `interview_recruitment_session_age_seconds` | Progress before the current call, when the warmup check was reached.                                                                                                   |

Reasons distinguish `legacy_protocol`, `url_unsupported`, `surface_excluded`, `internal_run`,
`task_bound`, `flag_disabled`, `flag_unavailable`, `invalid_configuration`, `configuration_unavailable`,
`not_product_call`, `missing_conversation`, `request_state_present`, `insufficient_tool_calls`,
`session_too_young`, `suppressed`, `reservation_conflict`, and `redis_error`.
`flag_unavailable` includes evaluation failures; it is not proof that the flag was evaluated as disabled.
Only the first failing gate is recorded. A call with `flag_disabled` can also lack URL support; use the
capability booleans to compare clients independently of the selected reason.

Legacy SSE calls evaluate eligibility before execution without reserving or showing an invitation.
Their tool-call diagnostics describe that check; `eligible` does not confirm an invitation. The server
rechecks eligibility after successful execution, including any privacy suppression learned from the API.
The existing `mcp interview invitation sent` event includes these diagnostics with reason `invited`.
A paused invitation has not executed a tool, so do not expect a completed tool-call event until its
continuation runs. Exec emits one tool-call event relabeled to the inner tool. Filter
`$mcp_exec_verb = 'call'` to exclude exec discovery commands, and include direct-tool events
separately. Private scout tools, impersonated requests, and analytics-suppressed calls do not expose
these diagnostics. No raw capability objects, tool arguments, or invitation answers are added.

Every event carries the authenticated user's distinct ID, `campaign_id`, `invitation_id`, and the `feature_flag`
key. The campaign comes from the selected variant and is retained for link opens and responses. Count distinct people for reach and invitation IDs for attempts. Invitations without a response
are unanswered, which can include abandonment, an open dialog, or a lost connection. An accepted
response records permission to open the link; it does not establish that the booking page opened.

The native dialog opens `/interview/<opaque UUID>` on the MCP host, which redirects to the configured
HTTPS booking URL. Redis holds the destination and identity for seven days. Unknown or expired links
return 404. Redirects disable caching and referrer forwarding, and HEAD requests do not count as opens.
A GET can also come from a link scanner; this is a measured redirect request, not proof of a human visit
or completed booking. Analytics delivery uses the SDK's normal best-effort pipeline and never blocks
the original tool or a known booking redirect. Suppressed and impersonated requests do not recruit.

To reset one user, delete that user's `:response` key and any matching
`:response:mcp-interview:*` pending keys. Disable the flag or finish any open invitation before
resetting. Do not reset all users just to test a change. Pending continuations expire after ten minutes
and are bound to the original token, tool arguments, organization, and project. A changed context
rejects the continuation before the tool runs. Consumed continuations retain a ten-minute marker
and cannot run again. Expired or consumed errors require checking the original tool's outcome
before retrying, because a write may already have succeeded. Replies on earlier protocols expire
after ten minutes and are bound to the authenticated user, PostHog instance, invitation, and original
token. They remain valid after project changes or flag changes because they cannot execute a tool.
Duplicate, expired, and mismatched replies do not update suppression or emit response events.

## Claude web and desktop exec schema budget

Claude web and desktop silently drop a tool when its serialized `inputSchema` reaches 16,384 characters, so the final `exec` input schema has a test budget below that limit.
Keep only guidance needed on nearly every call inline, including the compact tool-domain index.
Everything else belongs in the `learn` catalog: Claude web and desktop guides, and, behind the `mcp-exec-skills` flag, PostHog and project skills.
Skill names, descriptions, and bodies never go into the tool schema; agents discover them with `learn -s "<query>"` and read them with `learn <source>:<skill> [path]`.
Project skill search applies the caller's per-skill read permissions before ranking and limiting results; restricted skills contribute no metadata or excerpts.
The search endpoint uses dedicated burst and sustained budgets at the standard API rates (480 requests/minute and 4,800/hour). Personal API keys have separate budgets; OAuth and browser sessions share a budget per user. Exceeding either budget returns HTTP 429 with `Retry-After`, before the search runs.
The project skill API defaults to 8,000-character body pages. For `learn`, MCP requests up to 1,000,000 characters in one call, covering the API's 1 MB UTF-8 body limit, and rejects oversized or incomplete bodies before searching or formatting them. The separate 44,000-character display budget directs agents to search or read line ranges for larger files.

File reads and scoped searches scan lines incrementally. Search stops after 50 matches or when the display budget is full, preserving two context lines on either side where they fit. Heading outlines are bounded while being built, and oversized line ranges fail with a request to narrow the range. Files with many short lines do not require an array containing every line.
Do not trim endpoint serializers or generated tool schemas to meet the budget; they stay the source of truth for `info` and `schema`.

The eval runner's `--skill-delivery exec` mode removes bundled skills and defaults cases without an explicit interaction origin to the `eval` MCP consumer, which supports skill `learn`. Explicit case origins take precedence in both delivery modes. Bundled mode leaves unspecified origins unchanged.
The runner applies the selected delivery mode to both Python's sandbox-provisioning flag override and MCP's flag override. Bundled mode preserves native skills unless a case explicitly disables them; exec mode removes them. Compare the `expected_skill_loaded` and `skill_loaded_before_tool` scores: a completed eval run can report `PASS` despite zero scores unless `--fail-under` sets a score threshold.
The runner reports `FAIL` and exits with status 1 if a suite crashes or a case has an infrastructure error.
This rule applies even without a score threshold.
Infrastructure errors do not contribute to score averages.
Case timeouts and low scores affect the exit status only through `--fail-under`.
Temporary case setup failures and support-service readiness timeouts receive two retries by default, with delays of 1 second and 2 seconds.
Use `--infra-retries 0` to disable these retries.
Each case setup retry creates fresh test data before the agent starts.
The runner stops the previous service process before a readiness retry.
Retry messages show the next attempt and delay; only the final case result affects the error count.
Authentication errors, setup code errors, agent work, and low scores do not trigger these retries.
Bundled-mode evals explicitly disable `mcp-exec-skills` through the dev/test process override, which skips skill-catalog warmup and polling. Exec-mode evals allow 120 seconds for MCP startup, covering the 60-second warmup budget plus an in-flight download and development build; bundled mode keeps the 30-second startup limit. Production feature-flag evaluation does not control this process lifecycle.

## Rolling out MCP skill discovery

Deploy the Django skills API, task launcher, and MCP changes before enabling `mcp-exec-skills`.
Create or reuse a boolean flag with that exact key in the analytics project used by the two services; start disabled and enable a narrow user or organization condition first.
A missing flag evaluates as off. Development `FEATURE_FLAG_OVERRIDES` do not enable production behavior.

Verify the published skills archive loads, then start a new MCP session and sandbox task for an enabled user.
Exercise `learn -s`, a qualified skill read, and a product call, and check that a disabled user retains the prior behavior.
Skill use is advisory: a product `call` is never rejected for skipping `learn`, so stateless and session-holding clients behave the same.
Unknown learning topics and empty search queries return recovery instructions.
The `plugin` and `posthog-code` consumers remain excluded regardless of the flag.
Monitor archive validation errors, catalog size, MCP memory, and task failures before expanding the release condition.

To roll back access, disable the flag and start fresh sessions/tasks. This does not restore skills already removed from an existing sandbox.
Background cache behavior during rollback is described below.

## Shared skill archive cache

Each MCP process holds a parsed catalog in memory. Redis stores immutable archive bytes under a SHA-256 key and one JSON pointer containing the current SHA, ETag, and last successful upstream validation time. Writers store the bytes before replacing the pointer; readers fetch the named blob and verify its hash before using it. Polling an unchanged version never transfers the archive bytes.

For rollout and rollback, disabling `mcp-exec-skills` blocks caller access to product and project skills but does not unload the production catalog or stop archive polling. Stopping background catalog work requires a deployment change; restarting the same deployment reloads the catalog. The dev/test override described above does not apply in production.

The `v2` keys are separate from the earlier split-key layout, so a rolling deploy starts a new cache without changing the old processes' data. A failed write leaves the previous generation readable. Missing blobs trigger a full download; a 304 refresh extends the referenced blob's TTL and updates the pointer only if that pointer is still current. Old archive generations expire after the 30-day archive TTL. The context-mill slim manifest uses the same helper with its own namespace and seven-day TTL; its resource bodies remain keyed by URI.

The shared archive is checked for upstream changes after ten minutes. Use `mcp_skill_archive_last_validated_timestamp_seconds` to detect validation outages, including across process restarts. A successful 304 advances this timestamp. `mcp_skill_catalog_age_seconds` instead measures time since parsing and can grow while an unchanged archive remains healthy.

A candidate alert expression is `time() - mcp_skill_archive_last_validated_timestamp_seconds > 1800`, sustained for five minutes. Zero means the process has not observed a successful shared validation. Pair this with `mcp_skill_archive_events_total{result="error"}` and `mcp_skill_catalog_skills` when investigating. This metric does not prove that each process has adopted the latest archive. The alert must be configured in the monitoring system; exposing the metric does not send notifications.

## SQL-first MCP: HogQL system tables

Most list/get endpoints exposed as MCP tools should have a corresponding HogQL system table.
This lets agents query PostHog data via SQL in addition to (or instead of) the REST API tools.

Exceptions are OK when the tool intentionally proxies service-owned data,
aggregates data that is not represented as a team-scoped PostHog table,
or returns a curated API shape that would be awkward or unsafe to rebuild in SQL.
For these tools, keep the surface narrow and document the source and shape in the YAML description.

For proxy endpoints that can fail because of either user permissions or request scope,
return distinct API-visible error details. Agents should stop on true authorization
failures, but they can often recover from a bad project/team filter if the response says
the requested scope is unavailable.

The billing usage/spend proxy also returns recognized field-validation failures as
standard DRF validation errors (`type`, `code`, `attr`, `detail`). It keeps known
codes and public request fields, replaces upstream messages with controlled text,
and masks unrecognized failures. The shared MCP client handles these errors without
a billing-specific tool wrapper.

The billing usage/spend tools accept `usage_types` as an array of strings.
Their field description lists the accepted identifiers from `ee/billing/billing_types.py`, through the generated API schema.
The MCP client JSON-encodes the array for the HTTP API.
When both dates are omitted, the shared billing request serializer defaults usage/spend reads to the last 30 complete UTC days, ending yesterday.
Explicit date ranges are unchanged; a start date without an end date still ends today.
This also applies to the organization usage/spend time-series endpoints and CSV exports.
The billing overview, usage, and spend tools do not need a rollout flag.
API scopes and billing access checks still apply.

The underlying root billing API also supports an optional `organization_id` UUID on overview reads.
Use it when refreshing billing after a payment so another tab changing the user's current project cannot change the target.
The `billing-overview-get` tool does not expose it.
Subscription activation, payment authorization, and authorization status requests require an explicit `organization_id` in the body.
They reject missing or invalid IDs rather than falling back to the current project, and require billing access in the requested organization.
These payment actions remain unavailable to personal API keys and OAuth tokens.
The browser keeps the organization through Stripe redirects; payment links from older clients must be restarted from billing.

System tables are defined in [`posthog/hogql/database/schema/system.py`](https://github.com/PostHog/posthog/blob/master/posthog/hogql/database/schema/system.py) as `PostgresTable` instances.
Each table must include a `team_id` column for data isolation.

Example from the codebase:

```python
feature_flags: PostgresTable = PostgresTable(
    name="feature_flags",
    postgres_table_name="posthog_featureflag",
    fields={
        "id": IntegerDatabaseField(name="id"),
        "team_id": IntegerDatabaseField(name="team_id"),
        # ...
    },
)
```

Agents query these tables with the `system.` prefix:

```sql
SELECT id, key, name FROM system.feature_flags WHERE active = 1 LIMIT 10
```

### Extending query examples

When you add a new system table,
also add a model reference file to [`products/posthog_ai/skills/querying-posthog-data/references/`](https://github.com/PostHog/posthog/tree/master/products/posthog_ai/skills/querying-posthog-data/references).
The naming convention is `models-<domain>.md`.

Existing references:

- `models-actions.md`
- `models-cohorts.md`
- `models-dashboards-insights.md`
- `models-data-warehouse.md`
- `models-error-tracking.md`
- `models-flags-experiments.md`
- `models-groups.md`
- `models-notebooks.md`
- `models-surveys.md`
- `models-variables.md`

Each file documents the table's columns, types, nullability, and notable structures (like JSON fields).
See [`models-flags-experiments.md`](https://github.com/PostHog/posthog/blob/master/products/posthog_ai/skills/querying-posthog-data/references/models-flags-experiments.md) for a good example.
Register your new reference in [`products/posthog_ai/skills/querying-posthog-data/SKILL.md`](https://github.com/PostHog/posthog/blob/master/products/posthog_ai/skills/querying-posthog-data/SKILL.md) under **Data Schema**.

## Code generation pipeline

Generated handlers URL-encode path parameters. `ApiClient.request` also rejects empty path segments and paths that URL parsing would normalize. Keep generated calls on this client so the requested resource stays within the handler's endpoint.

The pipeline turns Django serializers into MCP tool handlers via OpenAPI.
Run the full pipeline with:

```sh
hogli build:openapi
```

### Pipeline steps

```text
build:openapi-schema     Django → OpenAPI JSON (frontend/tmp/openapi.json)
        │
        ▼
build:openapi-types      OpenAPI → TypeScript API types (frontend)
        │
        ▼
build:openapi-mcp        OpenAPI → Zod schemas for MCP (Orval)
        │
        ▼
build:openapi-mcp-tools  YAML definitions + Zod schemas → TypeScript tool handlers
```

### YAML definitions

YAML definitions are the configuration layer.
They live in **`products/<product>/mcp/*.yaml`**, keeping config close to the owning product's code.

> **Fallback path:** `services/mcp/definitions/*.yaml` is available for functionality that doesn't have a product folder.
> When a product folder exists, always place definitions there.

The build pipeline discovers YAML files from both paths.
Product teams own their definitions and control which operations are exposed as MCP tools.

**Workflow: add, configure, generate.**

1. **Add** the tools agents need.
   Tools are opt-in: an operation is exposed only when a YAML file has an entry for it.
   `--product` discovers endpoints by their **`x-product`** attribution —
   it matches endpoints whose product attribution equals the product name.
   ViewSets in `products/<name>/backend/` are auto-attributed via the module path.
   ViewSets elsewhere (e.g. `posthog/api/`, `ee/`) need
   `@extend_schema(extensions={"x-product": "<product>"})`.
   There is deliberately no URL-based matching — paths are a lossy signal of
   ownership and used to pull endpoints into the wrong product's tool list.

   The same applies when your product's API routes use a different slug than
   the product folder name (e.g. `workflows` product with `/hog_flows/` routes):
   add `@extend_schema(extensions={"x-product": "workflows"})` to the ViewSet so
   the scaffold can find them.

   ```sh
   # Only for a product with no YAML yet: create one with no tools
   pnpm --filter=@posthog/mcp run scaffold-yaml -- --product your_product \
       --output ../../products/your_product/mcp/tools.yaml
   # List the product's operations that have no YAML entry
   pnpm --filter=@posthog/mcp run scaffold-yaml -- --candidates --product your_product
   # Add one as an enabled tool
   # (--file <path> writes to a YAML file other than the product's tools.yaml)
   pnpm --filter=@posthog/mcp run scaffold-yaml -- --add your_product_things_list --product your_product
   ```

   To keep an operation off on purpose, for example when another tool supersedes it,
   give its entry `enabled: false` and `disabled_reason: <why>`.
   Sync removes an `enabled: false` entry without a `disabled_reason` as a leftover stub, and codegen rejects a `disabled_reason` on an enabled tool.

2. **Configure** each entry – the title and description come from the API; set them in the YAML when they do not read well for an agent.
   Scopes come from the API when you omit them. Annotations default for GET and DELETE, so declare them for PATCH, POST and PUT.
   A `scopes` list that misses a scope the API requires fails codegen.
   When an action's scopes depend on the request, list the action in the viewset's `request_dependent_scope_actions`, and declare `scopes` on its tools.
   A tool that reads ingested project data declares `reads_ingested_data`: `events`, or `events_or_warehouse` for a tool that also reads data warehouse tables.
   On a project that has not received an event yet, the server can return install guidance for these tools instead of an empty result.
   Every `query-*` tool must declare it.
   Each YAML file has a top-level structure validated by Zod ([`scripts/yaml-config-schema.ts`](https://github.com/PostHog/posthog/blob/master/services/mcp/scripts/yaml-config-schema.ts)):

   **Tool names** follow a **`domain-action`** convention in lowercase kebab-case (`[a-z0-9-]`),
   e.g. `feature-flags-list`, `experiments-create`, `surveys-delete`.
   The domain groups related tools together and the action describes the operation.
   Names must not start or end with a hyphen.

   **Feature identifiers** must be lowercase snake*case (`[a-z0-9*]`), e.g. `error_tracking`,
`feature_flags`. They should match the product folder name.

   **Tool name length limit:** tool names must be **52 characters or fewer**.
   This limit exists because MCP clients enforce different combined limits on server+tool name:

   | Client           | Limit                          | Notes                                                                 |
   | ---------------- | ------------------------------ | --------------------------------------------------------------------- |
   | MCP spec (draft) | 1–128 chars, `[A-Za-z0-9_\-.]` | Recommendation, not hard-enforced                                     |
   | Claude Code      | 64 chars                       | Prefixes tool names with `mcp____`                                    |
   | Cursor           | 60 chars combined              | `server_name + tool_name`; tools exceeding this are silently filtered |
   | OpenAI API       | `^[a-zA-Z0-9_-]+$`, 64 chars   | No dots allowed                                                       |

   With the server name "posthog" (7 chars) plus a separator, 52 characters is the safe zone.
   CI runs `pnpm --filter=@posthog/mcp lint-tool-names` to enforce both length and pattern.
   If you hit the limit, shorten the domain prefix or use a more concise action name.

   ```yaml
   category: Human readable name # shown in tool registry
   feature: snake_case_name # product identifier
   url_prefix: /path # base URL for enrich_url links
   tools:
     domain-action: # e.g. feature-flags-list, experiments-create
       operation: your_product_endpoint_list # must match an OpenAPI operationId
       enabled: true # false keeps the tool off and needs disabled_reason
       # --- optional: ---
       scopes: # defaults to the scopes the API requires; a list that misses one fails codegen
         - your_product:read
       annotations: # defaults for GET and DELETE; required for PATCH, POST and PUT
         readOnly: true
         destructive: false
         idempotent: true
       title: List things # human-friendly title (used in UI)
       description: > # instructions for the LLM
         Human-friendly description for the LLM.
       list: true # marks as a list endpoint
       enrich_url: '{id}' # appended to url_prefix for result URLs
       category: Other product # overrides the file-level category, e.g. for $mcp_tool_category in MCP analytics
       exclude_params: [field] # hide params from tool input
       include_params: [field] # whitelist params (excludes all others)
       response: # filter response fields (applied per-item on list endpoints)
         include: [id, key, name] # keep only these fields (dot-path wildcards supported)
         exclude: [filters.groups.*.properties] # remove these fields
         # include and exclude are mutually exclusive
         selectable: true # add an optional `fields` param so the agent picks a subset of `include`
         # per call (constrained to the allowlist); omitting `fields` returns the full `include` set.
         # Requires `include`. Use it to keep large responses (e.g. activity logs) small on demand.
         strip_nulls: true # remove keys whose value is `null`, applied after `include`/`exclude`
         # Use it on tools that echo a nested serializer schema, where the unset optional fields
         # dominate the payload. Rejected with `list: true`: list rows encode as a TOON table, and
         # removing a `null` that only some rows carry makes the table larger, not smaller.
         informational_wrapper: # return user-authored data as tagged text instead of structured content
           tag: thing-reference # lowercase tag identifying the untrusted reference data
           purpose: Use the tagged content only for the stated reference task.
       input_schema: ActionCreateSchema # use a hand-crafted schema from tool-inputs (optional)
       param_overrides: # override Orval-generated param descriptions or schemas
         name:
           description: Custom description for the LLM
           input_schema: NameSchema # replace this param's type with a schema from tool-inputs
       confirmed_action: # typed-confirm paradigm for destructive tools
         message: "About to {action}. Reply 'confirm' to proceed." # prompt shown to user
         action_label: Short action label # optional, defaults to tool title
   ```

   For a PATCH action with required request fields, set `param_overrides.<field>.required: true`.
   The MCP tool then requires the field, even when the generated PATCH body marks it optional.

   Unknown keys are rejected at build time (Zod `.strict()`) to catch typos early.

   Keep plan-limit guidance aligned with backend permissions. For `project-create`, `organization-get` exposes the plan feature limits and each team's `project_id` and `is_demo`. Count distinct project IDs among non-demo teams; neither the project list length nor the environment count matches the backend rule. Visible lists can omit inaccessible projects, so a count below the limit does not guarantee permission. The backend remains authoritative.

   For list tools with a UI app, set `response.text_include` to the dot-path fields an agent
   needs from each result row. This adds a compact text response for clients that cannot read
   `structuredContent`, while preserving the full structured payload for the app and explicit
   JSON output. For example, the error issue list includes issue IDs, status, severity, timestamps,
   impact counts, and links, but leaves volume buckets to the app. Pagination metadata stays in
   the text response, and `results[0]` explicitly identifies an empty page.

   For generated list apps, `generate:ui-apps` also checks `detail_tool` and the
   `detail_args` keys against the tool's input schema snapshot, so a wrong argument
   name fails generation instead of silently dropping the argument at runtime.
   See "UI apps" in `services/mcp/CONTRIBUTING.md` for the rules.

   A custom UI app can set `resource_domains` when it loads an image, font, script, or stylesheet from an external source. Each value must be a CSP source expression. Declare only the required origin or path.

   #### Custom input schemas

   By default, tool input schemas are auto-derived from OpenAPI via Orval.
   The generated exports in `src/generated/<product>/api.ts` are builder functions, so call them (`FeatureFlagsCreateBody()`) wherever you import one.
   A schema then exists only while a call uses it, and the server does not keep every schema in memory.
   When the auto-derived schema isn't ideal for an LLM tool interface,
   you can override it at two levels:

   **Whole-tool override** — set `input_schema` on the tool to a named export from `src/schema/tool-inputs.ts`.
   The generated handler imports that schema instead of composing Orval imports.
   The `operation` is still used for the HTTP method and path.
   Path parameters are extracted from the URL pattern;
   remaining parameters are forwarded as body (POST/PATCH/PUT) or query (GET/DELETE).

   **Per-param override** — set `input_schema` inside `param_overrides` to replace a single field's Zod type
   while keeping the rest of the Orval-derived schema.
   The generated code uses `.extend()` to replace just that field.
   See [supported annotations](https://modelcontextprotocol.io/specification/2025-06-18/schema#toolannotations) for the full list.

   #### Hooks for custom request logic

   The two overrides above reshape a generated tool's schema.
   Neither can change what happens around the request.
   `validators` runs as a synchronous `superRefine`, so it cannot await anything;
   `inject_body` supplies static values; `rename_params` only renames.

   When a tool has to read current state before writing, or handle a specific error, set `hooks:` on the tool.
   The value is a module path relative to `src/tools/`, without the extension:

   ```yaml
   update-feature-flag:
     operation: feature_flags_partial_update
     enabled: true
     hooks: featureFlags/updateFeatureFlagHooks
   ```

   The module default-exports an object with any of these functions, written `export default { beforeRequest } satisfies ToolHooks<Params>` so a misspelled name fails typecheck:

   - `beforeRequest(context, params)` returns the params the request should use.
   - `transformBody(context, params, body)` returns the body to send after the handler selects its declared fields. Use it when a read must supply fields the caller does not pass, such as an experiment's stored parameters and concurrency version.
   - `afterResponse(context, params, result)` returns the result to send to the client.
   - `onError(context, params, error)` returns a result that handles the error, or rethrows it.

   Codegen wraps the generated handler with them, so the name, schema and metadata stay generated.
   A `beforeRequest` that throws stops the request, and `onError` does not see that error.
   A `transformBody` that throws stops the request and reaches `onError`. When merging stored state, send the version read with that state and surface a conflict instead of retrying a stale body.
   `hooks` cannot be combined with `confirmed_action`.
   `src/tools/featureFlags/updateFeatureFlagHooks.ts` is the reference.
   Do not shadow a generated tool with a hand-written tool of the same name.

   The Logs tools use `logs/redactCredentialsHooks` to mask credentials in response strings and structured fields. This covers credential parameters, JSON and header values, URL passwords, bearer tokens, and private PostHog tokens. Nested URL encoding and JSON escaping do not bypass masking. The hook preserves unrelated text, except that strings with more than eight encoding layers are masked in full to bound parsing work. It does not change stored logs or responses outside MCP.

   #### Typed-confirm paradigm for destructive tools

   For destructive or security-sensitive tools (account changes, key revocation, bulk deletes),
   declare `confirmed_action` in the YAML config. The codegen emits two tools instead of one:
   - `<name>-prepare` – validates the arguments and returns a signed `confirmation_hash` plus a message for the user.
   - `<name>-execute` – accepts only the hash and the literal word "confirm" typed by the user, then performs the signed action.

   The model calls them in sequence: prepare → surface the message to the user → wait for "confirm" → execute.

   ```yaml
   tools:
     org-delete:
       operation: organizations_destroy
       enabled: true
       scopes: [organization_admin:write]
       annotations:
         readOnly: false
         destructive: true
         idempotent: false
       confirmed_action:
         message: "About to delete organization {orgId}. Reply 'confirm' to proceed."
         action_label: Delete organization
   ```

   **Fields:**
   - `message` (required) – prompt text shown to the user. Supports `{paramName}` placeholders interpolated from the validated tool args at runtime.
   - `action_label` (optional) – short human-readable label for the action (e.g. "delete project"). Surfaced in refusal messages. Defaults to the tool's title.

   **Security model:** the prepare step stashes the validated args and the active project/organization scope in Redis, and signs their SHA-256 digest together with the user identity, tool purpose, a TTL, and a single-use nonce into an HMAC-SHA256 token. The token stays small and constant-size no matter how large the args are, because the model relays only a reference to the payload. The execute step has a strict confirmation-only schema, verifies the signature, fetches-and-burns the stashed payload (the burn is the single-use enforcement), checks it against the signed digest, re-checks that the active scope still matches the one bound at prepare time, and only then runs the original handler with the verified payload. Action args belong only on prepare; extra execute-time fields are rejected, and a confirmation prepared while one project was active can't be replayed against another after `switch-project`.

   The confirmation word is supplied through model-authored tool arguments. This is an instruction-backed workflow guard, not client-attested proof that the human typed the word. API scopes remain the authorization boundary.

   **Constraints:**
   - Cannot combine `confirmed_action` with `input_schema` – custom input schemas do not use the confirmed-action codegen path yet.
   - Cannot combine `confirmed_action` with `ui_app` – the codegen doesn't wrap the execute factory with `withUiApp` yet.
   - Requires the `MCP_SIGNED_STATE_KEY` environment variable (≥32 bytes) on every environment running the MCP Hono server. A missing or short key disables the paradigm at boot (non-`confirmed_action` tools keep working), and `-prepare`/`-execute` calls fail at request time with a message pointing at the env var.

3. **Generate** handlers and schemas:

   ```sh
   hogli build:openapi
   ```

### Keeping definitions in sync

When backend API endpoints change, sync the YAML definitions:

```sh
pnpm --filter=@posthog/mcp run scaffold-yaml -- --sync-all
```

This is idempotent and never adds entries, so a new endpoint does not change any YAML file.
It keeps all hand-authored configuration, updates renumbered `_N` operation IDs,
removes a disabled entry whose operation is gone, and fails on an enabled tool whose operation is gone.
CI runs this as a drift check.

See [`services/mcp/definitions/README.md`](https://github.com/PostHog/posthog/blob/master/services/mcp/definitions/README.md) for the full YAML schema reference (note: YAML definitions themselves now live in product folders)
and [`services/mcp/scripts/yaml-config-schema.ts`](https://github.com/PostHog/posthog/blob/master/services/mcp/scripts/yaml-config-schema.ts) for the Zod validation source.

## Testing

The `query-llm-trace` and `query-llm-traces-list` wrappers bound the complete response to 80,000 characters for full detail and 60,000 characters for summary detail.
The limit includes the echoed query, warnings, and serialization of the MCP text content blocks, in either TOON or JSON output.
Summary previews use a 600-character budget per value.
These character budgets reduce response size but do not guarantee a token count; client limits and tokenization vary, so clients may still truncate responses or save them to a file.
Both modes can omit events, and large echoed filters or warnings can also be shortened.
Omission markers direct the agent to narrow the query or open the complete trace in PostHog.

See [How to develop and test](/handbook/engineering/ai/implementation#how-to-develop-and-test)
for instructions on running the MCP server locally and verifying tools end-to-end.

### Structured data for native tool widgets

For the `posthog_ai` consumer, tool responses carry the handler's returned data in
`_meta["com.posthog.mcp/app_data"]`, including tools without an MCP UI resource.
This applies to direct calls and calls through `exec`. The metadata excludes the
internal formatted-results override. The model receives the formatted text in `content`;
an explicit JSON output request still controls that text independently of widget data.
These responses omit the duplicate `structuredContent`. MCP tool spans exclude the
app-data metadata for this consumer while retaining model-visible output.

The agent forwards the MCP result through ACP's `rawOutput`. Claude and Codex adapters
preserve its metadata in live updates and history. When rebuilding a Claude model
transcript from ACP logs, the agent removes MCP result metadata before applying the
resume context budget. Metadata is available to widgets without becoming model input.
If widget metadata makes a task event exceed the transport size limit, the agent
removes that metadata and retries the size check. Text and status still reach the
client when the remaining event fits; events that remain oversized are dropped.

Native widgets read app data, existing `structuredContent`, or a direct result object.
They never decode TOON or JSON from result text.
The `execute-sql` backend returns the executed query in `structured_content` alongside its formatted text.
The MCP handler forwards that query as widget metadata, preserving resolved saved-variable definitions, `connectionId`, and `sendRawQuery`.
The widget renders it through the shared Query component in a `DataVisualizationNode`.
The Query component fetches the results for this visualization.
All query widgets require the executed query from the tool result. Old transcripts containing only text show the generic tool card.
Failed calls and missing or malformed widget data also use that fallback.
The web client resolves tool identity from ACP `_meta.posthog`, with legacy
`_meta.claudeCode` support. Non-exec MCP tools retain their qualified metadata names
to avoid collisions with built-in renderers. It retains `rawOutput` from both live updates and completed
`tool_call` frames in history.

Deploy MCP and agent transport support before deploying a frontend that requires
structured widget data. Verify both live calls and history replay, and inspect the
next model request to confirm that app metadata is absent.

## Serializer best practices

Descriptions flow through the entire pipeline:

```text
Django serializer field → OpenAPI spec → Zod schema → MCP tool description
```

Product teams should **type and describe** their serializer fields.
These descriptions are what agents read to understand tool parameters –
vague or missing descriptions lead to worse agent behavior.

See the [type system guide](/handbook/engineering/type-system) for the full backend → frontend pipeline,
including how to set up viewsets, serializers, and `@extend_schema` correctly.
For a comprehensive audit checklist, before/after examples, and detailed serializer/viewset patterns,
see the [`improving-drf-endpoints` skill](https://github.com/PostHog/posthog/blob/master/.agents/skills/improving-drf-endpoints/SKILL.md).

**Tips:**

- Use `help_text` on serializer fields – it becomes the OpenAPI description.
  Be careful when using imperative language in `help_text`,
  as the same annotations are used in the API docs.
- Use `param_overrides` in YAML definitions to override Orval-generated descriptions.
  This is useful when you want to add imperative instructions for specific fields.
- Be specific about formats, constraints, and valid values.
- Avoid jargon that an LLM wouldn't understand without context.
- `ListField` and `JSONField` need explicit types —
  use `ListField(child=serializers.CharField())` instead of bare `ListField()`,
  and `@extend_schema_field(PydanticModel)` on `JSONField` subclasses
  (see `posthog/api/alert.py` for the pattern).
  Without this, Orval generates `z.unknown()`.
- Plain `ViewSet` methods that validate manually need `@extend_schema(request=YourSerializer)` —
  without it, drf-spectacular can't discover the request body
  and the generated tool gets an empty schema with zero parameters.
  `ModelViewSet` with `serializer_class` works automatically.

### Defaults in partially updated settings

For JSON settings that merge on PATCH, leave nested `default` values out of the shared request schema.
Orval turns them into Zod defaults, so MCP sends values the caller omitted and overwrites stored settings.
For example, evaluation updates must preserve `allows_na` when the caller changes only `true_is_failure`, and vice versa.
Apply creation defaults in backend validation and describe them in the field's help text.

### Root-router viewsets

Viewsets mounted at root URLs (no `team_id`/`project_id` in the path) set
`param_derived_from_user_current_team` and are excluded from the OpenAPI schema by default,
which means they are invisible to frontend type generation and MCP tool scaffolding.
If your viewset is one of these and you want to expose it,
set `force_include_in_api_docs = True` on the class. See `ee/api/billing.py` for an example.
This flag only controls schema inclusion.
Runtime access still comes from the viewset's `scope_object`,
`scope_object_read_actions`, `scope_object_write_actions`,
and any per-action `required_scopes` or `dangerously_get_required_scopes` overrides.
Only mark the actions you actually want PATs, OAuth tokens, and MCP clients to call.

### MCP-only endpoints

An endpoint that is in the public schema becomes a REST contract: it shows up in Swagger, Redoc and the API docs, and people build on it.
To generate MCP tools and frontend types for an endpoint without that contract, mark it with `@extend_schema(extensions={"x-internal": True})`.
The codegen build (`hogli build:openapi`, which sets `OPENAPI_INCLUDE_INTERNAL=1`) keeps the operation.
The served `/api/schema/` drops it, the same way `@extend_schema(exclude=True)` does.
The marker only controls schema inclusion. The endpoint stays reachable, and auth and scopes still apply.

## HogQL query schemas (WIP)

[`frontend/src/queries/schema/schema-assistant-queries.ts`](https://github.com/PostHog/posthog/blob/master/frontend/src/queries/schema/schema-assistant-queries.ts) defines structured query types
for the AI assistant (trends, funnels, retention, events tables, etc.).

These schemas describe the shape of analytical queries with rich JSDoc comments
that help agents generate correct HogQL.
The cleaner and better-described these schemas are,
the better agents perform at query generation.

This is a work in progress –
the goal is to make it easier to generate HogQL queries from typed schemas
than from freeform SQL.
A `schema.json` integration into the codegen pipeline is planned.

## Agent skills that support the MCP server

- **`querying-posthog-data`** – HogQL query patterns, system model schemas, and available functions.
  Extend this skill to explain how agents should use your HogQL-exposed tables and queries.
  See [`products/posthog_ai/skills/querying-posthog-data/SKILL.md`](https://github.com/PostHog/posthog/blob/master/products/posthog_ai/skills/querying-posthog-data/SKILL.md).
- **`improving-drf-endpoints`** – Audit checklist and patterns for DRF serializers and viewsets.
  Use when editing or reviewing endpoints to ensure `help_text`, field types, and `@extend_schema` annotations
  flow correctly through the type pipeline.
  See [`.agents/skills/improving-drf-endpoints/SKILL.md`](https://github.com/PostHog/posthog/blob/master/.agents/skills/improving-drf-endpoints/SKILL.md).
