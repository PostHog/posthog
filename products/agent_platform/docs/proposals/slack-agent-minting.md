# Proposal: managed per-agent Slack apps

Status: draft proposal, not yet scheduled.
Owner: agent platform.

## Problem

Getting a Slack-triggered agent live today requires roughly ten manual steps across PostHog and Slack.
The user creates a Slack app, configures scopes, copies credentials, installs the app, sets two agent secrets, promotes the revision, and then returns to Slack to configure request URLs.
The promote-before-URL ordering trap is particularly confusing.

The goal is that a user can ask either the agent builder or the PostHog Slack app:

> Create a Slack agent named @JokerHog that tells jokes.

and receive a live PostHog agent with its own Slack name, avatar, and `@` handle.
The only per-agent Slack ceremony should be authorizing the new Slack app.

The Slack app is the agent's durable communication adapter and identity.
The PostHog agent application remains the product entity, and revisions continue to represent versioned behavior.

## Product entry points

Provisioning must not depend on starting inside Slack.
Both entry points call the same agent-builder workflow and connector control plane.

### From the agent builder

The builder authors the agent, asks the user to select a connected Slack workspace, requests provisioning, presents the authorization link, and monitors activation.

### From Slack

The existing PostHog Slack app supplies the Slack workspace, user, channel, and thread context, then starts the same builder task.
It remains a concierge and progress surface rather than becoming the runtime identity for every agent.

The builder never receives Slack configuration tokens, signing secrets, client secrets, or bot tokens.
It works with opaque enrollment and connector IDs through typed control-plane tools.

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
PostHog stores the pair through a secure enrollment form, rotates it when necessary, and uses it to call the same manifest APIs.

The access token is not needed at runtime after an app is created and installed.
The refresh chain is needed for future app creation, manifest updates, reconciliation, and deletion.

This enrollment is less smooth than the manager path but uses Slack's documented public API.
The token must never be pasted into Slack or an agent conversation.

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

1. **Author.** The builder creates or edits an agent with a Slack trigger.
2. **Select.** The origin supplies or asks for the target Slack workspace and optional channels.
3. **Enroll if needed.** The control plane checks provisioning authority. Manager enrollment is preferred; otherwise it returns a secure configuration-token enrollment URL.
4. **Mint.** The builder calls `slack-app-mint` with the application, revision, workspace, and enrollment IDs. The provisioner renders `buildSlackManifest()` with stable connector URLs and creates the child app.
5. **Authorize.** The user follows a one-time Slack OAuth URL for the child app.
6. **Install.** The callback verifies state and workspace identity, then stores the bot token and installation metadata on the connector.
7. **Activate.** An idempotent job updates `trusted_workspaces`, validates and freezes the target draft, promotes it, joins requested public channels, and reports completion.
8. **Run.** Slack routes `@JokerHog` events to the connector URL, which dispatches them to the application's live revision.

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

### Service placement

- Provisioning, installation, and lifecycle logic live in `products/agent_platform/backend/`.
- All Slack control-plane calls use a new `posthog/egress/slack/` transport.
- The existing `products/slack_app` integration only resolves Slack context, starts builder tasks, and reports progress.
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

- Add the enrollment, connector, and installation-attempt models.
- Add the provisioner interface and Slack egress transport.
- Add stable connector ingress routes and connector-based credential resolution.
- Add status and reconciliation primitives before exposing conversational creation.

### Phase B: provisioning strategy

- Implement the manager provisioner if Slack enables it.
- Otherwise implement secure configuration-token enrollment and serialized rotation.
- Add `slack-workspace-enrollment-status`, `slack-app-mint`, and `slack-app-status` endpoints and generated MCP tools.

### Phase C: installation and activation

- Add the state-bound OAuth callback and idempotent activation job.
- Add reinstall-required handling for scope expansion.
- Handle `tokens_revoked`, `app_uninstalled`, and Slack authentication failures.
- Add Connections-tab status, recovery, and teardown actions.

### Phase D: agent entry points

- Make the agent builder the canonical workflow for Slack deployment.
- Add the `@PostHog` lifecycle intent as a context-rich shortcut into that workflow.
- Rewrite the `setting-up-slack-app` playbook around the managed path while retaining the manual bring-your-own-app escape hatch.

### Testing and rollout

- Django tests for tenant isolation, OAuth state consumption, token rotation races, mint idempotency, and stale callback rejection.
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

## Open questions

- Can Slack enable the manager-app capability for PostHog, and is Vercel Connect using the same program?
- Should configuration-token enrollment recommend or require a service account?
- Should the connector credential broker replace revision-level Slack secrets immediately or through a compatibility phase?
- Where should workspace-level enrollment and minted-app inventory live in the UI?
- When a user starts from the builder, how should they choose channels before the child app is installed?
