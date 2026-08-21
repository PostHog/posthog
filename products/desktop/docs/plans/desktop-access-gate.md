# PostHog Desktop access gate

## Goal

Remove the Desktop waitlist and access-code requirement.

Access is bound to the selected project and its organization. A user can access Desktop unless the organization:

- has a `Startup` or `YC` program label, or
- has prepaid credits that are pending, or paid with an active, unexpired, nonzero balance.

The backend-evaluated `posthog-desktop-access-override` flag grants access before either restriction. Flag targeting remains operational configuration and is not hardcoded.

## Current flags

Live status checked in PostHog project 2 through MCP:

| Flag | Rollout | Change |
| --- | --- | --- |
| `tasks` | Active, targeted allowlist | Remove from Desktop authorization. |
| `loops` | Active, 100% | Keep independent from Desktop authorization. |
| `tasks-prewarm-sandbox` | Active, 100% | Keep independent from Desktop authorization. |
| `pi-harness` | Active, effectively 100% | Keep independent from Desktop authorization. |
| `posthog-desktop-access-gate` | Active, 0%, organization-bucketed | Roll out progressively after deployment. |
| `posthog-desktop-access-override` | Active, 0% | Target approved exceptions only. |

## Existing work to reuse

`@adboio` has no open PostHog PRs. The relevant work is already merged into `master`:

- [#80720](https://github.com/PostHog/posthog/pull/80720) and [#84466](https://github.com/PostHog/posthog/pull/84466) make the selected Desktop project authoritative and send it as `X-PostHog-Project-Id` on gateway requests. Reuse this header and auth state instead of adding another project-selection mechanism.
- [#80720](https://github.com/PostHog/posthog/pull/80720) also validates OAuth scope, live organization membership, and project access control before rebinding the gateway user to the selected `team_id`. Run the Desktop gate only after this validation.
- [#84469](https://github.com/PostHog/posthog/pull/84469) and [#85508](https://github.com/PostHog/posthog/pull/85508) make authenticated team attribution authoritative. Key access checks, caches, billing reads, and logs from the validated team, never caller metadata or task ID alone.
- [#71343](https://github.com/PostHog/posthog/pull/71343) provides stable gateway error envelopes and legacy-client compatibility. Extend that machine-readable pattern for Desktop access reasons instead of parsing messages.
- [#80978](https://github.com/PostHog/posthog/pull/80978) contains Desktop billing-denial classification and admin-aware actions. Reuse its error transport and billing navigation where useful, while keeping the new whole-app access screen separate from usage-limit modals.
- [#70951](https://github.com/PostHog/posthog/pull/70951) and [#81573](https://github.com/PostHog/posthog/pull/81573) establish `internal_run:read` as the server-minted credential marker. Keep this marker as the human-versus-background boundary instead of checking the shared OAuth application ID.
- [#77438](https://github.com/PostHog/posthog/pull/77438) establishes organization-scoped Desktop billing. [#69324](https://github.com/PostHog/posthog/pull/69324) provides the team-aware credit-bucket resolver and quota backstop. Reuse their scope and failure patterns, but do not treat usage exhaustion as prepaid-credit ownership.

## Backend contract

Django is the authoritative policy boundary. Add a project-scoped endpoint:

```text
GET /api/projects/{project_id}/desktop/access/
```

It returns `allowed` and one of these nullable reasons:

- `startup_plan`
- `prepaid_credits`

Evaluate access in this order:

1. Validate project membership and token scopes.
2. When `posthog-desktop-access-gate` is off, preserve the existing `tasks` flag and `CodeInviteRedemption` decision.
3. Allow when `posthog-desktop-access-override` evaluates to true for the user and selected organization.
4. Block `Startup` and `YC` organizations with `startup_plan`.
5. Block pending prepaid credits or active paid prepaid balances with `prepaid_credits`.
6. Allow all other organizations.

`startup_plan` takes priority if both restrictions apply. Exhausted or expired prepaid credits do not block access.

Billing and feature-flag failures return a service error, not a business rejection. Cloud compute and direct model access fail closed while Desktop shows a retryable technical state.

Billing owns the funding classification through a product-neutral, organization-authorized endpoint:

```text
GET /api/billing/funding-status/
```

It returns the existing `startup_program_label` (`Startup`, `YC`, or `null`) and a normalized prepaid state: `none`, `pending`, `active`, `exhausted`, or `expired`. Billing does not know about Desktop access or rejection reasons.

The funding endpoint derives prepaid state from credit records, pending purchase state, synced balance, and actual expiration time. Stripe customer balance is fungible, so an unexpired paid prepaid credit plus a positive synchronized customer balance reports `active`, including mixed-credit balances. This conservative rule avoids inventing unsupported balance attribution. The existing credit-purchase overview is not an authorization contract and must not be reused as one.

A generic PostHog Billing adapter validates and caches this contract by organization. The Desktop policy maps funding state to its own rejection reasons. It must not duplicate Billing rules or infer prepaid status from Desktop usage, `discount_amount_usd`, or AI gateway wallets.

## Access-code retirement

Access codes remain a rollout fallback but do not override the new policy.

- Keep the `tasks` flag and `CodeInviteRedemption` in access decisions while `posthog-desktop-access-gate` is off.
- Remove the invite-code onboarding step and standalone screen.
- Show invite-code redemption within the access screen for a legacy denial.
- Ignore redemptions for authorization after the rollout flag is enabled.
- Stop accepting new public redemptions after the compatibility window.
- Keep all existing access-code models, migrations, records, tables, admin pages, and historical data.

Keep `/api/code/invites/check-access/` and `/api/code/invites/redeem/` unchanged for released clients. The new project endpoint returns `allowed: false` with a null reason for a legacy denial.

## Enforcement boundaries

Apply the gate to human-triggered operations that can allocate cloud resources or cause model spend:

- run or prewarm a cloud task,
- create, start, or resume a cloud run,
- obtain a sandbox connection token,
- send model-driving commands or messages,
- call the `posthog_code` LLM gateway product directly.

Keep harmless reads and local task operations available. Existing authentication, project scopes, throttles, compute quotas, and Desktop usage limits remain active.

Preserve trusted PostHog-run workloads:

- Server-minted `internal_run:read` credentials bypass the human gateway gate.
- Wizard, scouts, Inbox, workflows, and other background tasks keep their trusted task paths.
- Inbox exemptions still require server-verifiable task relationships or reserved server-created origins.
- Client-provided `origin_product` never grants access.

Update the LLM gateway resolver to return the full decision and call the project-scoped endpoint with the already validated `AuthenticatedUser.team_id`. Cache by token or user and team, matching the existing selected-project authorization boundary. Preserve `code_access_required` for released clients and add the backend denial reason to the existing machine-readable gateway error envelope. Deploy the Django project endpoint everywhere before deploying the revised gateway; old gateway instances continue using the compatibility endpoint during that rollout. Update `services/llm-gateway/PARITY.md` with the revised contract.

## Desktop behavior

Replace `hasCodeAccess` with a typed state containing the selected project, result, and rejection reason.

Check access after authentication and after every project or organization change. Recheck on retry after technical failures.

The blocked screen has separate Startup and prepaid-credit variants. It shows the selected project and organization and provides:

- organization and project switchers stacked vertically,
- retry for technical failures,
- invite-code redemption for legacy denials while the rollout flag is off,
- the account executive and `sales@posthog.com` contact path for prepaid-credit access requests, and
- logout.

Reuse the existing auth state and project-switch mutations from the sidebar switcher. Switching selection updates the server-side current organization and runs the project-scoped check again. Logging out remains available, but users do not need to log out to select an eligible organization.

## Abuse protection

- Fail closed for compute and direct model calls when policy resolution fails.
- Check project membership before evaluating billing access.
- Cache by user and team, never by user alone.
- Cache denials for less time than grants, and do not cache resolution failures.
- Preserve task and gateway throttles and usage limits.
- Require trusted server provenance for task exemptions.
- Record allow, denial reason, override, and resolution-failure outcomes without billing details or secrets.

## Tests

Add a parameterized Django policy matrix for normal, Startup, YC, pending prepaid, active prepaid, exhausted, expired, combined restrictions, override, failures, legacy access, and one user switching between organizations.

Keep regression coverage for each cloud-spend endpoint and trusted Inbox and background-task exemptions.

Test gateway team-aware caching, reason forwarding, fail-closed behavior, internal-run bypass, and isolation from other products.

Test Desktop reason rendering, project and organization switching, legacy invite redemption, technical retry, and successful entry after selecting an eligible project.

## Rollout

1. Create the rollout and override flags without targeting anyone.
2. Deploy the product-neutral Billing funding-status endpoint.
3. Add the Django resolver and project-scoped backend contract.
4. Route task enforcement through the authoritative `posthog-desktop-access-gate` decision, which starts with no targeting.
5. Deploy the revised gateway only after the project endpoint is deployed everywhere.
6. Release Desktop support for reasons, switching, and technical failures.
7. Progressively target the rollout flag and monitor decisions and resolution failures.
8. Stop new access-code redemptions after the compatibility window.
9. Remove compatibility client code later while retaining historical access-code data.
