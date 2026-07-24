# Proposal: managed per-agent Slack apps

Status: draft proposal, not yet scheduled.
Owner: agent platform.

## Problem

Getting a Slack-triggered agent live today requires roughly ten manual steps across PostHog and Slack.
The user creates a Slack app, configures scopes, copies credentials, installs the app, sets two agent secrets, promotes the revision, and then returns to Slack to configure request URLs.
The promote-before-URL ordering trap is particularly confusing.

The goal is that a user can ask from any agent-authoring surface, including the agent builder or the PostHog Slack app:

> Create a Slack agent named @JokerHog that tells jokes.

and receive a live PostHog agent with its own Slack name, avatar, and `@` handle.
The only per-agent Slack ceremony should be authorizing the new Slack app.

The Slack app is the agent's durable communication adapter and identity.
The PostHog agent application remains the product entity, and revisions continue to represent versioned behavior.

## Authoring surfaces and control-plane contract

Provisioning must not depend on starting inside Slack or using the PostHog Code UI.
The canonical implementation is the connector control-plane API and its generated MCP tools.
The agent builder, PostHog Slack app, PostHog Code, CLI clients, and future authoring experiences are clients of the same contract.

The origin contributes context and chooses how to present progress and required user input:

- The agent builder can ask the user to select a connected Slack workspace and render installation progress inline.
- The existing PostHog Slack app can supply the Slack workspace, user, channel, and thread context, then report progress in the originating thread.
- An API or MCP client can provide its own user experience while driving the same lifecycle.

The existing PostHog Slack app remains a concierge rather than becoming the runtime identity for every agent.
No authoring agent or conversation receives Slack configuration tokens, signing secrets, client secrets, bot tokens, or other submitted secret values.
Clients work with opaque request, enrollment, and connector IDs through typed control-plane tools.

## Surface-independent user input

Agent authoring frequently needs input that does not belong in a text conversation, including secrets, OAuth authorization, files, confirmations, and structured configuration.
Slack provisioning should use a general transient-input primitive rather than hardcode a PostHog Code secrets punchout.

When provisioning needs configuration credentials, the control plane creates an expiring, single-use input request that declares:

- The fields or authorization required.
- Which values are secret.
- The authenticated user or team allowed to complete it.
- The storage destination for submitted values.
- Expiration, consumption, and cancellation state.
- The status and non-sensitive metadata that the requesting agent may observe.

For example:

```text
AgentInputRequest
- team_id
- requested_by_user_id
- kind: secret | oauth | file | confirmation | structured_input
- schema
- destination_type
- destination_id
- expires_at
- consumed_at
- status
```

The active client decides how to render the request:

- An inline protected form in PostHog Code.
- A builder UI app.
- A temporary page hosted alongside the agent experience.
- A short-lived browser handoff from Slack.
- A CLI prompt or customer-owned UI.

Presentation is surface-specific, but submission and custody are not.
Secret values submit directly to a platform-controlled endpoint, are encrypted into the declared destination, and are never returned to the authoring agent, MCP tool result, conversation history, or general agent runtime.
An agent-hosted page may compose the experience, but agent-authored code must not receive the submitted secret values.

The requesting workflow receives only state such as `pending`, `completed`, `expired`, or `cancelled`, then resumes from the corresponding opaque resource ID.
The PostHog Code punchout is therefore one renderer for this contract, not the required authoring surface.

## Prior art: Vercel Connect and Eve

Eve delegates its Slack integration to Vercel Connect rather than implementing Slack provisioning in the Eve runtime.
`eve channels add slack` creates a connector through the Vercel CLI, waits for a workspace installation, and attaches the Eve route as the connector's trigger destination.
At runtime, `connectSlackCredentials()` retrieves the outbound credential from Connect and verifies inbound Connect-forwarded requests with Vercel OIDC.

Vercel's current documentation says Connect creates and manages the Slack app, lets the user name it, stores its credentials, receives Slack webhooks, and forwards verified events to attached projects.
The earlier assumption that all Eve agents share one global Slack bot identity was incorrect.
A connector is closer to the application-level Slack adapter proposed here.

The useful separation is:

1. **Workspace connection:** authority to provision or install Slack applications.
2. **Connector:** a Slack application, credentials, scopes, events, and installation state.
3. **Destination:** the project or agent application that receives events.

PostHog should copy this separation even if Slack does not offer us the same workspace-authorization flow that Vercel uses.

References:

- [Build a Slack bot with Vercel Connect](https://vercel.com/kb/guide/build-a-slack-bot-with-vercel-connect)
- [Eve Slack channel](https://github.com/vercel/eve/blob/main/docs/channels/slack.mdx)
- [`@vercel/connect` SDK](https://github.com/vercel/vercel/tree/main/packages/connect)

## Slack provisioning authority

The Slack manifest APIs support two conceptually similar provisioning strategies.
The rest of the connector lifecycle should not depend on which one is available.

### Preferred investigation: manager app

Slack's current API references describe manager apps that create and manage child apps:

- `apps.manifest.create` documents manager enrollment, managed-app limits, and workspace feature enablement.
- App approval requests can identify the `manager_app_id` that provisioned a child.
- Enterprise administrators can preapprove future child apps from a manager.
- Manager credentials can update, export, and delete only children created by that manager.

However, Slack does not publicly document how an app enrolls, how manager configuration credentials are issued, whether the program is generally available, or whether a distributed app can create children inside independently owned installation workspaces.
The feature appears gated and must be confirmed directly with Slack.

If available, the existing PostHog Slack app is the natural manager and conversational front door.
It would create child apps such as `@JokerHog`, while each child remains the runtime connector for its agent.

References:

- [`apps.manifest.create`](https://docs.slack.dev/reference/methods/apps.manifest.create/)
- [`app_configurations:write`](https://docs.slack.dev/reference/scopes/app_configurations.write/)
- [Managing app approvals](https://docs.slack.dev/admins/managing-app-approvals/)

### Documented fallback: workspace configuration token

A Slack user with app-creation rights generates a configuration access token and refresh token for a workspace.
The control plane creates a secret input request targeting a `SlackAppProvisioningEnrollment`.
Whichever client is driving the workflow renders that request and submits the pair directly to encrypted enrollment storage.
PostHog rotates the credentials when necessary and uses them to call the same manifest APIs.

The access token is not needed at runtime after an app is created and installed.
The refresh chain is needed for future app creation, manifest updates, reconciliation, and deletion.

This enrollment is less smooth than the manager path but uses Slack's documented public API.
The token must never be pasted into an agent conversation or returned through an agent tool call.
Clients that cannot safely render secret input should use a short-lived browser handoff rather than accepting the credential as conversational text.

References:

- [Configuring apps with app manifests](https://docs.slack.dev/app-manifests/configuring-apps-with-app-manifests/)
- [`tooling.tokens.rotate`](https://docs.slack.dev/reference/methods/tooling.tokens.rotate/)

### Common provisioner contract

The control plane should isolate the credential source behind one interface:

```python
class SlackAppProvisioner(Protocol):
    def create_app(self, *, workspace_id: str, manifest: dict[str, object]) -> ProvisionedSlackApp: ...
    def update_app(self, *, slack_app_id: str, manifest: dict[str, object]) -> None: ...
    def delete_app(self, *, slack_app_id: str) -> None: ...
```

Initial implementations:

- `ManagerAppSlackProvisioner`, if Slack enables the capability for PostHog.
- `ConfigurationTokenSlackProvisioner`, as the documented fallback.

Both return the child app ID, client credentials, and signing secret.
Changing provisioning strategy must not require rebuilding installation, ingress, activation, or revision handling.

## Connector architecture

### Application-level ownership

Slack credentials belong to the agent application, not an individual revision.
A new `AgentSlackConnector` is the durable relationship between a PostHog agent and its Slack app.

Suggested shape:

```text
AgentSlackConnector
- team_id
- application_id
- enrollment_id
- slack_workspace_id
- slack_app_id
- public_routing_id
- client_id
- client_secret
- signing_secret
- bot_token
- bot_user_id
- installed_scopes
- desired_scopes
- status
```

Use a unique constraint on `(application_id, slack_workspace_id)`.
The connector is the source of truth for Slack credentials.
If the first implementation must continue using the revision secret resolver, promotion may materialize connector credentials into the target revision, but revision storage should remain a compatibility layer.

### Stable ingress URLs

Every minted manifest uses connector-level URLs that do not change across revisions:

```text
https://agents.posthog.com/slack/<public-routing-id>/events
https://agents.posthog.com/slack/<public-routing-id>/interactivity
```

The route resolves the connector, verifies the Slack signature with its signing secret, and answers `url_verification` before the application has a live revision.
Normal events resolve `application.live_revision` and dispatch to the existing Slack trigger runtime.

This avoids the current preview-JWT mismatch, prevents draft revisions from receiving production Slack traffic, and removes the promote-before-URL ordering trap.

### Installation attempts

OAuth installation state must be expiring and single-use.
Store it as a durable `SlackInstallAttempt` bound to:

- PostHog team and user.
- Connector and child Slack app ID.
- Expected Slack workspace ID.
- Target application and revision.
- Nonce, expiry, and consumption time.

The callback verifies the returned Slack workspace and app, atomically consumes the attempt, stores installation credentials, and schedules activation after the database transaction commits.
It must reject stale callbacks rather than promoting a revision that has since been replaced.

## End-to-end flow

1. **Author.** Any authoring client creates or edits an agent with a Slack trigger through the shared control-plane contract.
2. **Select.** The origin supplies or asks for the target Slack workspace and optional channels.
3. **Request input if needed.** The control plane checks provisioning authority. Manager enrollment is preferred; otherwise it creates an expiring secret input request targeting a workspace enrollment.
4. **Render and submit.** The active client renders the request inline or through a short-lived handoff. Credentials submit directly to encrypted control-plane storage, and the authoring agent observes only completion status.
5. **Mint.** The client calls `slack-app-mint` with the application, revision, workspace, and enrollment IDs. The provisioner renders `buildSlackManifest()` with stable connector URLs and creates the child app.
6. **Authorize.** The client renders or links the one-time Slack OAuth request for the child app.
7. **Install.** The callback verifies state and workspace identity, then stores the bot token and installation metadata on the connector.
8. **Activate.** An idempotent job updates `trusted_workspaces`, validates and freezes the target draft, promotes it, joins requested public channels, and reports completion.
9. **Run.** Slack routes `@JokerHog` events to the connector URL, which dispatches them to the application's live revision.

The configuration token or manager credential is never used on the runtime message path.

## Revision and scope changes

New revisions reuse the same connector, Slack app, bot identity, and stable URLs.
Before promotion, compare the revision's desired Slack capabilities with the connector's installed scopes and event subscriptions.

- If capabilities are unchanged or reduced, promote normally.
- If scopes expand, update the manifest and set `reinstall_required`.
- Complete reauthorization before promoting behavior that depends on the new scopes.
- Never point Slack request URLs directly at a draft revision.

## Models and service boundaries

### `SlackAppProvisioningEnrollment`

Team-scoped association between a PostHog project and Slack workspace provisioning authority.
It stores the strategy, encrypted credential payload, expiry, enrolling user, manager app ID where applicable, and status.

Initially, configuration-token enrollment should remain project-specific.
If one Slack workspace connects to multiple PostHog projects, require distinct token chains rather than copying one refresh token into multiple rows.
Organization-level sharing can be added later with an explicit authorization model.

### `AgentSlackConnector`

Application-level Slack app and installation record.
It drives status UI, ingress resolution, reinstall requirements, revocation, and teardown.

### `SlackInstallAttempt`

Single-use installation state used by the unauthenticated child-app OAuth callback.

### `AgentInputRequest`

Expiring request for input that should not be represented as ordinary conversational text.
It records the schema, authorized submitter, opaque storage destination, lifecycle state, and non-sensitive status exposed to the requesting workflow.
The first use case is Slack configuration-token enrollment, but the contract should support OAuth, file uploads, confirmations, and other structured authoring interactions.

### Service placement

- Provisioning, installation, and lifecycle logic live in `products/agent_platform/backend/`.
- All Slack control-plane calls use a new `posthog/egress/slack/` transport.
- The connector control-plane API and generated MCP tools are the canonical lifecycle interface.
- Authoring clients render input requests and progress without handling submitted secret values.
- The existing `products/slack_app` integration only resolves Slack context, starts authoring workflows, and reports progress.
- Agent ingress owns stable connector webhook routes and runtime dispatch.

## Build plan

### Phase 0: Slack capability spike

Before committing to either enrollment UX:

1. Ask Slack whether PostHog can enroll its existing distributed app as a manager.
2. Confirm whether a manager can provision children inside customer installation workspaces or only its home team.
3. Confirm the manager credential type, rotation model, enrollment process, limits, and child behavior after parent uninstall.
4. Test `apps.manifest.create` response credentials and request URL validation in a Slack sandbox.
5. Test configuration-token ownership when the enrolling user loses permission or leaves the workspace.
6. Confirm creation, update, deletion, and rate limits for both available strategies.

### Phase A: common connector foundation

- Add the enrollment, connector, installation-attempt, and transient-input models.
- Add the provisioner interface and Slack egress transport.
- Add stable connector ingress routes and connector-based credential resolution.
- Add status and reconciliation primitives before exposing conversational creation.

### Phase B: surface-independent input

- Add an expiring input-request contract with typed schemas and opaque destinations.
- Add a protected submission endpoint that writes secrets directly to destination-specific encrypted storage.
- Expose only request metadata and completion state through API and MCP tools.
- Implement PostHog Code inline rendering as one client, plus a generic short-lived browser handoff for clients without secure input components.
- Ensure agent sessions, tool traces, analytics, and logs never capture submitted secret values.

### Phase C: provisioning strategy

- Implement the manager provisioner if Slack enables it.
- Otherwise implement secure configuration-token enrollment and serialized rotation.
- Add `slack-workspace-enrollment-status`, `slack-app-mint`, and `slack-app-status` endpoints and generated MCP tools.

### Phase D: installation and activation

- Add the state-bound OAuth callback and idempotent activation job.
- Add reinstall-required handling for scope expansion.
- Handle `tokens_revoked`, `app_uninstalled`, and Slack authentication failures.
- Add Connections-tab status, recovery, and teardown actions.

### Phase E: authoring clients

- Make the agent builder, PostHog Code, and generated MCP tools clients of the canonical control-plane lifecycle.
- Add the `@PostHog` lifecycle intent as a context-rich client of the same contract.
- Rewrite the `setting-up-slack-app` playbook around the managed path while retaining the manual bring-your-own-app escape hatch.

### Testing and rollout

- Django tests for tenant isolation, OAuth state consumption, token rotation races, mint idempotency, and stale callback rejection.
- Input-request tests for authorization, expiry, single-use submission, destination binding, redaction, and agent-visible status.
- Agent ingress tests for pre-live URL verification, signature validation, inactive connectors, and live revision routing.
- End-to-end tests for mint, install, activation, revision promotion, reinstall-required, revocation, and deletion.
- Feature-flag the full path and dogfood with an internal agent before broader rollout.

## Risks

1. **Manager availability.** Slack's references describe the feature, but enrollment and distributed-workspace behavior are undocumented. Treat it as an optimization until Slack confirms access.
2. **Configuration credential custody.** The fallback grants workspace app-creation authority. Encrypt it, route calls through egress controls, audit every lifecycle operation, and fail closed.
3. **Credential ownership.** User-bound configuration credentials may fail when the enrolling user leaves or loses permission. Surface re-enrollment explicitly.
4. **Ambiguous creates.** `apps.manifest.create` is not documented as idempotent. Do not blindly retry an ambiguous timeout; preserve a reconciliation state.
5. **Stale installation callbacks.** An old authorization link must not overwrite a newer installation or promote an outdated revision.
6. **Workspace app sprawl.** Provide consistent naming, managed-by metadata, inventory, and best-effort cleanup with retries.
7. **Scope changes.** Updating a manifest may require reauthorization. Model `reinstall_required` as a real connector state rather than relying only on a thread message.
8. **Secret exposure through renderers.** A flexible rendering model creates more places where values could be logged or captured. Keep submission platform-controlled, make secret fields non-observable to agent code, and require renderers to opt out of analytics and replay capture.
9. **Over-generalizing the first implementation.** Slack enrollment should establish the reusable request contract without delaying provisioning on a complete form-building platform.

## Open questions

- Can Slack enable the manager-app capability for PostHog, and is Vercel Connect using the same program?
- Should configuration-token enrollment recommend or require a service account?
- Should configuration credentials be retained for automatic lifecycle management or requested just in time for each manifest operation?
- Should the connector credential broker replace revision-level Slack secrets immediately or through a compatibility phase?
- Which authoring clients should render secret requests inline in the first release, and which should use the generic browser handoff?
- How should workspace-level enrollment and minted-app inventory surface consistently across clients?
- When a user starts from the builder, how should they choose channels before the child app is installed?
