# Growth account audits: workflow and HTTP trigger plan

## Context

The Growth Temporal workflow exists in this draft. It takes an organization ID, a project team ID, and an acting user ID. It starts a private task without a repository. The task uses the latest single-file `onboarding-account-audit` skill from project 2. The workflow waits for the task, checks its notebook in the audited project, and captures `audit_finished` with `organization_id`, `team_id`, and `notebook_url`.

The skill is not present yet. The workflow stops before task creation if it cannot read the skill. No user interface, HTTP trigger, or email sender exists in this draft. The task origin uses the internal AI gateway product and does not consume customer task credits.

The goal of the next phase is to start this workflow from a PostHog Workflows event in project 2. A later Workflows workflow can use `audit_finished` to send a message. These are two separate flows.

## Findings

- Workflows already has an HTTP Webhook action. It supports a fixed URL, POST, a JSON body, and Standard Webhooks signatures. The `signing_secret` input is encrypted.
- The action does not send a PostHog user identity or credential. A signed request proves possession of the signing secret, not that a Django user has `is_staff=True`.
- The action's normal `headers` input is **not secret**. The web workflow API returns its contents. Do not store a personal API key or a static bearer token there.
- Outbound HTTP requests block private network addresses. Use a public HTTPS app endpoint, not a private service hostname. The destination must be reachable in the chosen region.
- Workflows can retry a POST after an ambiguous network failure. Standard Webhooks keeps `webhook-id` stable across retries. The receiver must use that ID to prevent a second audit.
- The current Temporal workflow blocks a second run while its organization workflow ID is active. It permits a new run after completion. It does not enforce a seven-day limit.
- The task needs a real acting user. It now checks that the user is active, belongs to the organization, and can read the audited project. A Workflows person ID is not that Django user ID.
- The existing project 2 `account-audit` skill describes a different, multi-session process. This workflow expects a new, single-file `onboarding-account-audit` skill. Its content must arrive before any live run.

## Decision for the next phase

Use the existing HTTP Webhook action. Add one purpose-specific Growth POST endpoint. Do **not** change the Workflows product for this phase.

Authenticate the endpoint with Standard Webhooks signatures. Put one strong signing secret in the Workflows action's secret input and in server configuration. Reject requests when either side has no secret. The endpoint must compare the HMAC over the **raw body** with constant-time comparison. It must reject missing or malformed headers and timestamps outside a short window. Rotate the secret if it is disclosed. A shared secret gives the caller broad audit-start authority, so limit who can edit this workflow and keep a server kill switch.

Do not use `is_staff` as the only gate. A webhook has no Django staff user. A staff-owned personal API key in the normal headers field would expose that key to readers of the workflow graph. If the requirement is to authorize each call as a named staff user, this generic action is not sufficient without a safe credential mechanism. Use a dedicated Workflows action with a scoped service token in that case.

Proposed request:

```text
POST /api/growth_account_audits/start/
Content-Type: application/json
webhook-id: <stable delivery ID>
webhook-timestamp: <Unix time>
webhook-signature: v1,<base64 signature>

{"organization_id":"<organization UUID>","team_id":<project team ID>}
```

The workflow URL stays fixed. The body contains only the two IDs. Do not send the full triggering event or person record. The endpoint checks that the project belongs to the organization and that the organization has approved AI data processing. It must not trust an event field as staff identity or as an acting user ID.

**Open decision:** Choose the acting user. One option is a designated user with approved access to every audited project. Another is a server-selected eligible organization member. Do not infer the user from a Workflows person ID, email address, or event field. The endpoint cannot safely call the existing facade until this policy is set.

## Admission and responses

Add a Growth-owned audit admission record when the actor policy is set. Serialize admission by organization. Store the signed `webhook-id`, target organization and team, Temporal workflow ID, and admission time. Do not dispatch until the admission record commits. Recover a record if Temporal dispatch fails after the commit.

- A repeat `webhook-id` returns the same workflow ID without a new task. Return `202`.
- A different request while an audit runs returns `409`. Do not start another task.
- A new request within seven days of the last admission returns `409` with the next allowed time. Count failed runs until a deliberate retry policy replaces this rule. Do not return `429`: Workflows retries that status.
- Invalid signatures return `401`. Invalid targets or missing AI approval do not dispatch.
- Set a rate limit and a server kill switch. These protect against a loop or a leaked signing secret. Workflows trigger masking can reduce duplicate events, but it does not replace server admission.

The project 2 workflow must not use event fields to set the destination URL. Only trusted editors can change its signing secret. A dedicated secret is not proof that an event's target IDs are true. Check those IDs on the server before every start. Start with one Cloud region; confirm cross-region routing and skill availability before an EU launch.

## Completion, delivery, and visibility

The Temporal workflow emits `audit_finished` only after it checks that the task completed and saved a new notebook in the audited project. The completion event has a stable insert ID for retry safety. A separate Workflows workflow can send an email from that event. Before delivery, confirm that the recipient can open the notebook. An internal notebook URL alone does not give an external recipient access.

For scout access, keep notebook discovery project-scoped. A follow-up can tell the scout fleet that a notebook exists through a project-level signal or saved resource. Do not add customer-specific notebook links to global MCP tool descriptions or cached agent instructions.

## Implementation sequence

1. Publish the reviewed `onboarding-account-audit` skill in project 2. Keep it in one file. Confirm that notebook MCP tools work in a test project.
2. Choose the acting-user policy. Add the signed Growth endpoint, durable admission record, kill switch, and rate limit. Keep all authorization and target checks on the server.
3. Configure a project 2 Workflows HTTP Webhook step with the fixed HTTPS URL, a small JSON body, and its encrypted signing secret. Keep request debugging off.
4. Add the completion-event workflow and a delivery rule after notebook access and the recipient are defined. Do not send an email from the audit task.
5. Add project-scoped notebook discovery for scouts only after a real audit proves the notebook useful.

## Tests and verification

Test signature validity, altered bodies, stale timestamps, missing secrets, wrong-region targets, actor eligibility, AI approval, and organization/project mismatch. Test repeated delivery IDs, concurrent deliveries, a failed Temporal dispatch, an active audit, and the seven-day boundary. Assert that no rejected request starts a task. Assert that a failed or empty notebook emits no `audit_finished` event.

Before a live rollout, start one approved test audit. Check its skill version, run origin, notebook content and access, `audit_finished` event, and customer credit report. Check that a repeated signed POST produces no second run. Only then enable the project 2 event trigger. After rollout, inspect successful audits, failed runs, missing notebooks, duplicate rejects, and email delivery separately.
