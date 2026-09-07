# Notebook widget permissions TODO

## Product contract

- [x] Add three independent generation toggles:
  - [x] Access this notebook's dataframes, enabled by default.
  - [x] Make arbitrary HogQL queries, disabled by default.
  - [x] Make PostHog tool calls, disabled by default.
- [x] Serialize disabled dataframe access as `<Widget noDataFrames />`.
- [x] Serialize enabled HogQL and tool access as explicit attributes on the Widget tag, using names consistent with the notebook parser.
- [x] Preserve these permissions when improving or regenerating a widget, while allowing the user to change them for the new immutable version.
- [x] Apply the same permissions when an agent creates a follow-up generation prompt.
- [x] Keep API-enabled generated widgets unavailable in public notebook shares.

## Generation and review

- [x] Persist the permission snapshot on generation jobs and immutable widget versions.
- [x] Include the permissions in generation idempotency and restore behavior.
- [x] Give the generation model instructions for only the capabilities the user enabled.
- [x] When tool calls are enabled, let the generation model search and inspect the PostHog MCP tool catalog during its existing generation run.
- [x] Do not run another LLM when a generated widget executes.
- [x] Update static validation and model security review to understand dataframe, HogQL, and tool permissions.
- [x] Flag dynamic tool names, unrelated tools, writes during render or polling, destructive calls without confirmation, data exfiltration, and excessive queries.

## Runtime

- [x] Continue exposing paginated notebook data through `ph.readFrame` only when dataframe access is enabled.
- [x] Reuse the Canvas host bridge for deterministic `ph.query` calls when HogQL access is enabled.
- [x] Add deterministic `ph.tools.call(toolName, input)` calls backed by the PostHog MCP catalog when tool access is enabled.
- [x] Keep authentication in the trusted host/backend so the sandboxed iframe never receives a private token.
- [x] Validate the current viewer, team, notebook, widget version, build hash, declared permissions, tool schema, and tool scopes on every request.
- [x] Require generated writes to follow explicit user interaction and destructive confirmation patterns, and flag violations during verification.
- [x] Keep direct network access, `fetch`, `XMLHttpRequest`, and undeclared Canvas methods blocked.
- [x] Bound concurrency, request count, response bytes, pagination, and timeouts.

## UI and examples

- [x] Add the toggles to the initial widget form and the improve/regenerate modal using existing Lemon form controls.
- [x] Explain that HogQL and tool calls run with the current viewer's PostHog permissions.
- [x] Show enabled permissions in the exact-build verification step.
- [x] Add demos for a live HogQL visualization, an MCP-backed action, and a widget that combines notebook data with live PostHog data.

## Validation

- [x] Extend focused backend tests for serialization, defaults, immutable versions, restore, idempotency, permission enforcement, and sharing.
- [x] Extend focused frontend tests for toggle defaults, Widget attributes, prompt inheritance, and bridge routing.
- [x] Extend Canvas builder/runtime tests for capability-specific SDK exposure and rejection.
- [x] Verify that runtime HogQL and tool calls are deterministic and do not start an agent or LLM run.
- [x] Regenerate OpenAPI and Kea types where their source contracts change.
- [x] Run focused tests, frontend formatting, frontend type checking, migration checks, and CI preflight.
- [ ] Render and exercise the flow in the browser, including before/after screenshots with synthetic data. Blocked locally because the in-app browser bridge could not initialize its sandbox metadata.
- [x] Update `docs/internal/generated-notebook-widgets.md` and the Canvas SDK documentation.
