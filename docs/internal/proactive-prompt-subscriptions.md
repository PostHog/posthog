# Proactive prompt subscriptions

Proactive prompt subscriptions extend a scheduled AI report with up to three recommended next steps. A run may also prepare one local code change, one draft pull request, or one inert experiment draft when its rollout controls allow that artifact.

The feature is disabled by default. Do not enable it for customer teams until the controlled-runtime gate below passes.

## Standing consent

The subscription owner enables proactive follow-up while creating or editing an AI report subscription. This is standing consent for future deliveries; there is no approval step on each run.

Automatic draft pull requests require an exact repository selected from repositories the current user can push to through their personal GitHub connection. Saving the subscription creates a revocable, versioned grant for that repository. Another editor may disable automatic pull requests, but changing the repository requires their own current authorization.

Public web research is enabled by default for new proactive configurations. Existing configurations remain off until an owner enables it, preserving their previous consent boundary. The owner can turn it off to keep analysis within PostHog data. The analysis chooses from server-owned topics, which PostHog maps to fixed public queries; model-authored workspace content never reaches Firecrawl.

Enabling proactive follow-up also permits an eligible run to prepare an inert experiment draft. The operation always creates a new inactive flag, leaves experiment dates unset, and sends no traffic.

## Configuration UI

The `subscription-creation-wizard` experiment splits creation into Report, Actions, Notify, Schedule, and Review. Actions appears only for AI reports when proactive follow-up is available. Review shows the standing action consent before creation.

Report suggestions describe outcomes such as activation, adoption, conversion, retention, and regressions. They remain editable and use the existing prompt field. When enabled, the first report can run immediately after the subscription is created.

Actions shows unavailable capabilities with their current setup requirement. Public web research uses one default-on switch; it does not require source setup. Draft pull requests remain limited to authorized repositories.

Editing uses Content, Actions, Delivery, and Settings tabs under the same experiment. A saved Actions configuration remains visible when the server capability becomes unavailable so the owner can turn it off. All sections share one form and one persistent Save action; hidden validation errors move the user to the affected section.

## Delivery timing

The scheduled report, proactive analysis, recommendations, and artifacts produce one immutable delivery bundle. The destination renderer reads that bundle once at the delivery cutoff. Artifact reconciliation may update subscription history later, but it does not send a second message.

Each delivery may create at most one proactive run, one task, one analysis task run, one execution task run, three recommendations, one draft pull request, and one experiment draft. Overlapping deliveries do not start a second active run for the same subscription.

## Billing

Pulse sandbox runs use the reserved `pulse_subscription` task origin and the PostHog AI gateway product. Their model usage consumes the organization's AI credits under the existing AI spend limit. Generic `task_analysis` runs remain PostHog-funded and excluded from customer usage.

## Safety boundaries

- The sandbox receives no GitHub token, authenticated remote, or general PostHog write scope.
- PostHog reads use reviewed, bounded MCP presets. Person data, recordings, secrets, billing, and organization administration are excluded.
- Public research uses a task-bound MCP operation backed by Firecrawl. It is offered only when Firecrawl is configured. The broker accepts only server-owned topics, validates public HTTP(S) targets and redirects, and returns one bounded untrusted excerpt.
- A run can make at most three research calls. Completed retries reuse stored evidence; concurrent identical requests and exhausted budgets return a controlled conflict without another provider call. Stale claims recover only after the provider deadline has elapsed.
- The sandbox has no raw web or shell HTTP access. The broker holds the provider credential, enforces the per-run call budget, and records retry-safe evidence.
- Repository execution happens in a credential-free workspace. Publication happens through the Tasks broker after required repository gates and the public-output scan pass.
- The broker can create one draft pull request in the granted repository. It cannot merge it, mark it ready, update an existing pull request, or publish to another repository.
- The experiment operation is create-only. It cannot reuse or activate a feature flag or update an existing experiment.
- History exposes verified artifact and public-source links only. It never returns raw evidence bodies, storage references, credentials, or model reasoning.

Public repositories make generated code, branch names, commit messages, pull request text, and uploaded assets visible outside PostHog. Controlled runs must use invented data and repositories approved for public output.

## Rollout controls

`PULSE_PROACTIVE_ENABLED` is the master eligibility switch. The integrated release keeps it disabled.

Keep the master switch off until every analytics-platform worker has deployed the Pulse workflow and activity registry. For an isolated rollout, provision `PULSE_TASK_QUEUE` pollers before routing child workflows to that queue. See `docs/internal/proactive-pulse-operations.md` for the required two-deployment sequence.

The following independent switches take effect only when the master switch is enabled:

- `PULSE_DRAFT_PR_ENABLED` controls brokered draft pull request publication.
- `PULSE_EXPERIMENT_DRAFT_ENABLED` controls inert experiment creation.
- `PULSE_PUBLIC_RESEARCH_ENABLED` is the server-wide kill switch for public web research. A subscription-level switch provides the owner opt-out.

Limits are controlled by the `PULSE_MAX_*` settings in `posthog/settings/subscriptions.py`. Lower a limit or disable the relevant switch before investigating abnormal volume, cost, or failures. Disabling artifact switches must not stop the scheduled report or recommendation history.

The default wall-clock budget is 60 minutes. Draft pull request runs reserve the final 20 minutes before finalization for protected repository checks and brokered publication. If implementation does not finish before that cutoff, the run fails closed without publishing.

## Controlled-runtime gate

Before enabling the master switch, run a scheduled delivery in a controlled team and repository and verify all of the following:

1. The report persists before proactive work starts.
2. The run performs an audited PostHog read through the reviewed preset.
3. Public research uses only the task-bound MCP operation and a server-owned topic, stays within configured limits and its total provider deadline, rejects private or non-standard network targets, and honors the subscription opt-out.
4. The preserved workspace builds and runs every required repository test gate.
5. The broker creates exactly one draft pull request with no sandbox credential.
6. The optional experiment is new, inactive, has no dates, and exposes no traffic.
7. The destination receives one logical immutable bundle.
8. History shows authoritative task and artifact state, including partial failures and the current draft pull request state.
9. Revoking the repository grant or GitHub access prevents publication at credential time.
10. Disabling each artifact switch leaves report delivery and recommendations available.

Repeat the deterministic fake coverage in pull request CI. Inspect every generated diff and artifact manually during controlled dogfood.

## Rollback

Disable `PULSE_PROACTIVE_ENABLED` to stop new runs. Existing report subscriptions continue on their normal schedule, and completed history remains readable.

For a narrower rollback, disable the affected artifact or research switch. Revoke active repository grants when publication authorization must end immediately. Draft pull requests and inert experiments already created remain user-owned artifacts and require an explicit human decision to close or delete.
