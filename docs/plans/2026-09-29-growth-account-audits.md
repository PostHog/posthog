# Growth account audits: workflow and HTTP trigger plan

## Context

The Growth Temporal workflow and signed HTTP entry point exist in this draft. The entry point takes an organization ID and a project team ID. It selects an eligible project member as the agent actor and starts a private task without a repository. The task uses the latest single-file `onboarding-account-audit` skill from project 2. The workflow waits for the task, checks its notebook in the audited project, and captures `audit_finished` with `organization_id`, `team_id`, and `notebook_url`.

The skill is not present yet. The HTTP entry point rejects a new admission if it cannot read the skill. No user interface, configured Workflows trigger, or email sender exists in this draft. The task origin uses the internal AI gateway product and does not consume customer task credits.

A project 2 Workflows event can call the signed HTTP entry point after a credential is provisioned. A separate Workflows workflow can use `audit_finished` to send a message. These are two separate flows.

## Findings

- Workflows already has an HTTP Webhook action. It supports a fixed URL, POST, a JSON body, and Standard Webhooks signatures. The `signing_secret` input is encrypted.
- The action can send `Authorization: Bearer <personal API key>`, but its `headers` input is **not secret**. The web workflow API returns its contents. Log redaction does not protect the stored key.
- The action does not support a secret Bearer input today. Editing a saved Data Pipelines destination does not change the shared template that Workflows runs. The Workflows documentation suggests broader destination support than the current template-based runtime provides.
- The existing `signing_secret` input is encrypted. A signed request proves possession of that secret, not that a Django user has `is_staff=True`.
- Outbound HTTP requests block private network addresses. Use a public HTTPS app endpoint, not a private service hostname. The destination must be reachable in the chosen region.
- Workflows can retry a POST after an ambiguous network failure. Standard Webhooks keeps `webhook-id` stable across retries. The receiver must use that ID to prevent a second audit.
- The signed endpoint stores a delivery ID and reserves a Temporal workflow ID. It blocks new admissions for seven days. A retry uses the reserved ID, so it cannot start a second workflow after the first one finishes.
- `Task.team` and `Notebook.team` determine project ownership. Their `created_by` fields record people, not ownership.
- Signals research and implementation run as real users with effective access to the target project. Tasks mints a project-scoped OAuth token for that actor. The audit now uses the same approach: Signals selects an eligible organization member, and the audit task runs as that member. Staff trigger authority stays on the separate signed credential. This is not a new service credential. The member appears as the task and notebook creator, so the UI must not present them as the staff initiator.
- The existing project 2 `account-audit` skill describes a different, multi-session process. This workflow expects a new, single-file `onboarding-account-audit` skill. Its content must arrive before any live run.

## Selected trigger design

Use the existing HTTP Webhook action and its Standard Webhooks signing secret. Growth exposes one purpose-specific POST endpoint. Do **not** change the Workflows product or the shared HTTP Webhook template for this phase.

Put one strong signing secret in the Workflows action's secret input and in server configuration. Reject requests when either side has no secret. The endpoint must compare the HMAC over the **raw body** with constant-time comparison. It must reject missing or malformed headers and timestamps outside a short window. Rotate the secret if it is disclosed. Keep a server kill switch.

A signing secret belongs to a workflow step by default, not to a user. Growth binds each issued secret to an active staff owner and a project 2 workflow in an encrypted credential record. The endpoint selects that record with a public key ID. It verifies the signature, checks that the workflow is active in project 2, and rechecks the owner's `is_staff` status on every request. An owner who loses staff status cannot use the credential. The staff owner is accountable for this integration, but the signature does not identify the person who caused an event to fire.

Only staff should edit the workflow or its trigger. Use a trusted event source that non-staff cannot use to start an audit. If a non-staff user can emit the matching event, Workflows will sign the resulting request. The endpoint cannot infer the event emitter's role from the signature. Keep the destination URL fixed and do not accept an event-provided user ID.

**Not selected:** A Bearer personal API key in the HTTP step's normal headers. Those headers are returned by the web workflow API. An encrypted Bearer field would require a shared CDP template change. It would still let an editor send the token to another public URL.

Proposed request:

```text
POST /api/growth_account_audits/start/
Content-Type: application/json
webhook-id: <stable delivery ID>
webhook-timestamp: <Unix time>
webhook-signature: v1,<base64 signature>
X-PostHog-Audit-Key: <issued key ID>

{"organization_id":"<organization UUID>","team_id":<project team ID>}
```

The workflow URL stays fixed. The body contains only the target IDs. Do not send the full triggering event or person record. The endpoint checks that the project belongs to the organization and that the organization has approved AI data processing. It must not trust an event field as staff identity or as an acting user ID.

**Execution identity:** Staff control the trigger; an eligible audited-project member supplies the agent's MCP identity. Signals already selects a member for its research and implementation tasks. Growth calls that Signals resolver through its facade. The audit task and notebook use the audited team ID. The task OAuth token is scoped to that team and member. Growth rechecks the member's access and AI approval before task creation. If no eligible member exists, the endpoint refuses the request.

This reuses Signals' user-bound credential model, but it attributes the task and notebook to the selected member. The staff credential owner remains the recorded initiator on the Growth admission. Do not claim that the selected member requested the audit. The signed request does not accept a member ID or a Workflows person ID.

## Admission and responses

Growth stores an admission record before it asks Temporal to start. It serializes admission by organization and stores the signed `webhook-id`, target, reserved workflow ID, and admission time. A same-delivery retry uses that reserved ID. If Temporal cannot answer, the endpoint returns `503` and keeps the record for a retry. The current implementation has no separate background retry after Workflows exhausts its HTTP retries; add operator recovery before a broad rollout.

- A repeat `webhook-id` returns the same workflow ID without a new task. Return `202`.
- A different request while an audit runs returns `409`. Do not start another task.
- A new request within seven days of the last admission returns `409` with the next allowed time. Count failed runs until a deliberate retry policy replaces this rule. Do not return `429`: Workflows retries that status.
- Invalid signatures, revoked credentials, and owners who are no longer staff return `401`. Invalid targets or missing AI approval do not dispatch.
- The endpoint uses an IP rate limit. Disabling the Growth credential is the kill switch. Workflows trigger masking can reduce duplicate events, but it does not replace server admission.

The project 2 workflow must not use event fields to set the destination URL. Only trusted staff editors can change its signing secret. A staff-bound secret does not prove that an event's target IDs are true. Check those IDs on the server before every start. Start with one Cloud region; confirm cross-region routing and skill availability before an EU launch.

## Completion, delivery, and visibility

The Temporal workflow emits `audit_finished` only after it checks that the task completed and saved a new notebook in the audited project. The completion event has a stable insert ID for retry safety. A separate Workflows workflow can send an email from that event. Before delivery, confirm that the recipient can open the notebook. An internal notebook URL alone does not give an external recipient access.

For scout access, keep notebook discovery project-scoped. A follow-up can tell the scout fleet that a notebook exists through a project-level signal or saved resource. Do not add customer-specific notebook links to global MCP tool descriptions or cached agent instructions.

## Implementation sequence

1. Publish the reviewed `onboarding-account-audit` skill in project 2. Keep it in one file. Confirm that notebook MCP tools work in a test project.
2. Test the Signals member resolver against an audited project. Confirm the task OAuth token is bound to that project. Keep staff initiator attribution on the Growth admission.
3. Provision a staff-bound signing credential for an active project 2 workflow. Configure the HTTP step with the fixed HTTPS URL, a small JSON body, the issued key ID header, and its encrypted signing secret. Keep request debugging off.
4. Restrict workflow editing and the trigger event source to staff-controlled paths. Add a way to recover a pending admission after HTTP retries are exhausted.
5. Add the completion-event workflow and a delivery rule after notebook access and the recipient are defined. Do not send an email from the audit task.
6. Add project-scoped notebook discovery for scouts only after a real audit proves the notebook useful.

## Tests and verification

Test signature validity, altered bodies, stale timestamps, missing secrets, revoked staff owners, workflow editing rights, untrusted event sources, wrong-region targets, Signals actor eligibility, team-bound OAuth access, AI approval, and organization/project mismatch. Test repeated delivery IDs, concurrent deliveries, a failed Temporal dispatch, an active audit, and the seven-day boundary. Assert that no rejected request starts a task. Assert that a failed or empty notebook emits no `audit_finished` event.

Before a live rollout, start one approved test audit. Check its skill version, run origin, notebook content and access, `audit_finished` event, and customer credit report. Check that a repeated signed POST produces no second run. Only then enable the project 2 event trigger. After rollout, inspect successful audits, failed runs, missing notebooks, duplicate rejects, and email delivery separately.
