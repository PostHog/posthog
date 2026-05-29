# Onboarding activation analysis & experiment proposals

_Investigation date: 2026-05-29. Window: last 30 days of signups. Source: PostHog
production "PostHog App + Website" project (id 2) via MCP. Test accounts filtered,
funnel window 14 days unless noted._

## TL;DR

- **3.6%** of signups complete onboarding inside 14 days (signup → `onboarding completed`).
- **26.6%** fire their first SDK event — the truer "activation" milestone for downstream retention.
- Two giant addressable drop-offs: **(1)** 39% of signups never reach the onboarding scene at all
  (signup → `onboarding started`), and **(2)** 73% of users who reach the install step click
  "Skip installation" rather than wait for SDK verification.
- The top 3 experiment bets are: a forced-redirect / continuity nudge from signup to
  onboarding, a copy + behaviour change on the install-skip button, and a wizard-first
  install variant that handles SDK install without copy-paste.

## 1. The current onboarding flow

The flow is orchestrated by `frontend/src/scenes/onboarding/onboardingLogic.tsx` and is
URL-driven: `/onboarding/<productKey>?step=<stepId>&with=<secondaries>`. The set of steps
is assembled dynamically per product by a registry of step providers
(`stepProviderRegistry`) plus shared trailing steps (`appendSharedTrailingSteps`).

Canonical step keys (`OnboardingStepKey`, see `frontend/src/types.ts:7223`):

| Step key             | What it is                                                                 |
| -------------------- | -------------------------------------------------------------------------- |
| `install`            | SDK install instructions + live verification (`first team event ingested`) |
| `link_data`          | Data warehouse source connection (DWH-only)                                |
| `plans`              | Billing plan selection (Cloud, when not already subscribed)                |
| `verify`             | Realtime "we saw your event" check (variant of install)                    |
| `configure`          | Product-specific config (e.g. session replay opt-ins)                      |
| `proxy`              | Reverse proxy setup (skippable)                                            |
| `invite_teammates`   | Invite teammates                                                           |
| `session_replay`     | Toggle session replay opt-ins                                              |
| `authorized_domains` | Toolbar-authorised domains                                                 |
| `source_maps`        | Error tracking source maps (skippable)                                     |
| `alerts`             | Error tracking alerts (skippable)                                          |

Pre-onboarding the user passes through `productSelection`, which fires
`onboarding started` (with `entrypoint=product_selection`) before the flow begins.

### Events fired at each stage (the ones we can actually measure)

| Event                              | Where it fires                                                                 | Useful props                |
| ---------------------------------- | ------------------------------------------------------------------------------ | --------------------------- |
| `user signed up`                   | Backend on signup completion                                                   | `is_organization_first_user`, `referral_source`, `signup_social_provider` |
| `onboarding started`               | `productSelectionLogic.ts:317` — when product selection scene mounts           | `entrypoint`                |
| `onboarding product toggled`       | Each product selection toggle                                                  | `productKey`, `selected`    |
| `onboarding_products_confirmed`    | After clicking continue on product selection                                   |                             |
| `onboarding step completed`        | `OnboardingStep.tsx:62`, `NextButton.tsx:29`, `PlanCards.tsx:99`, others       | `step_key`, `product_key`   |
| `onboarding step skipped`          | `OnboardingStep.tsx:56`, `NextButton.tsx:35-36` ("Skip installation" CTA; event fires at `:24`) | `step_key`, `product_key`   |
| `onboarding adblock detection completed` | `useAdblockDetection.ts:57` on install scene                             | `status`                    |
| `first team event ingested`        | Backend, on first event from a new team                                        | (system property)           |
| `subscribed during onboarding`     | Listener on billing callback `success=true`                                    | `productKey`                |
| `onboarding exit modal opened`     | When user clicks the leave-onboarding affordance                               | `step_at_open`              |
| `onboarding completed`             | `onboardingLogic.tsx:511` after the user clicks "Finish" on the last step      | `productKey`                |
| `product intent marked activated`  | Backend — when the team passes a per-product activation threshold              | `product_type`              |
| `post_onboarding_modal_shown`/`cta_clicked`/`dismissed` | Post-completion modal                                      |                             |

## 2. Activation funnel (last 30d, 14d conversion window)

Series: `user signed up` → `onboarding started` → `onboarding step completed` →
`first team event ingested` → `onboarding completed` (ordered, 14-day window).

| # | Step                          | Users  | % of signups | Step-over-step |
| - | ----------------------------- | ------ | ------------ | -------------- |
| 1 | `user signed up`              | 72,823 | 100.0%       | —              |
| 2 | `onboarding started`          | 44,555 | 61.2%        | **−38.8%**     |
| 3 | `onboarding step completed`   | 30,317 | 41.6%        | −31.9%         |
| 4 | `first team event ingested`   | 19,378 | 26.6%        | −36.1%         |
| 5 | `onboarding completed`        |  2,599 |  **3.6%**    | **−86.6%**     |

### How to read this

- **Activation rate ≈ 26.6%** if defined as "fired the first event within 14d of signup". This
  is the metric that maps to downstream retention and revenue and the one we recommend
  experiments target.
- The headline 3.6% `onboarding completed` rate is **not** a fair measure of activation —
  the flow only fires `onboarding completed` when the user clicks the final **Finish**
  button. Many users land their first event and then navigate away into the product
  (dashboards, replays, etc.) without returning to click Finish. Compare:
  - Funnel-window unique users reaching `onboarding completed`: 2,599
  - Unique-user-days firing `onboarding completed` over 30d (no funnel window): ~35,468
  - Unique-user-days firing `product intent marked activated`: ~10,831

  The funnel attribution under-counts true completion by roughly an order of magnitude.

### Per-product breakdown (start at `onboarding started`)

Step-completion (col 2) is near-universal because every flow auto-fires at least one
`onboarding step completed`. The product-level signal is the **first-event-rate** (col 3):

| Product           | Started | Step ✓ | First event | Onboarding ✓ |
| ----------------- | ------: | -----: | ----------: | -----------: |
| product_analytics | 7,924   | 98%    | **61%**     | 7%           |
| session_replay    | 1,411   | 99%    | 56%         | 6%           |
| logs              | 1,365   | 100%   | 54%         | 7%           |
| web_analytics     | 1,220   | 99%    | 59%         | 8%           |
| llm_analytics     |   343   | 99%    | **33%**     | 3%           |
| feature_flags     |   233   | 99%    | 46%         | 4%           |
| error_tracking    |   155   | 100%   | 54%         | 11%          |
| surveys           |    73   | 100%   | 47%         | 3%           |
| experiments       |    68   | 96%    | 43%         | 4%           |

LLM analytics is the worst-performing product onboarding by a wide margin
(33% first-event rate vs ~55-61% baseline), and feature flags trails too.

### Step skip rates (last 30d, unique users)

`onboarding step completed` vs `onboarding step skipped`, broken down by `step_key`:

| Step key             | Completed | Skipped | Skip share |
| -------------------- | --------: | ------: | ---------: |
| `install`            |    11,785 |  31,396 | **72.7%**  |
| `link_data`          |       422 |  25,386 | 98.4%      |
| `authorized_domains` |     2,626 |   1,772 | 40.3%      |
| `source_maps`        |        46 |     397 | 89.6%      |
| `alerts`             |         0 |     396 | 100%       |
| `invite_teammates`   |    33,467 |       0 | 0% *       |
| `configure`          |    32,206 |       0 | 0% *       |
| `plans`              |    29,078 |       0 | 0% *       |

\* "completed" includes auto-advances by `goToNextStep` even when the user did nothing
on the step. `invite_teammates`, `configure`, and `plans` don't expose an explicit Skip
CTA — they always fire `completed` on advance.

The `install` row is the headline finding: **73% of users who reach the install step click
"Skip installation"** (`NextButton.tsx:35` — text varies by `installationComplete` state).
The button only switches to "Next" once the realtime verifier sees an event from the
team. The skip path still advances the flow, so most of these users go on to be counted
as activated via async first events — but they leave the install step unverified.

### Time to convert (median, unbreakdown funnel)

| Transition                                          | Median           | Mean            |
| --------------------------------------------------- | ---------------- | --------------- |
| `user signed up` → `onboarding started`             | ~5 s             | ~62 min         |
| `onboarding started` → `onboarding step completed`  | ~4.5 min         | ~45 min         |
| `onboarding step completed` → `first team event`    | ~35 min          | ~14 hours       |
| `first team event` → `onboarding completed`         | ~3 min (when it happens) | ~13 hours |

Long tails dominate the means. The median for "see first event" is ~35 minutes after
finishing the first step — that's plausibly the time it takes a developer to copy-paste
the SDK snippet, deploy, refresh, and trigger an event.

## 3. Top drop-off points (ranked by users lost × addressability)

### Drop-off A — signup → onboarding scene (28,268 users / 30d)

39% of signups never fire `onboarding started`. Hypotheses:

1. **Email-verification stall.** Users who sign up via email need to click a verification
   link before the onboarding URL loads cleanly. If they read the email later (or never),
   they sit in a "signed up, not started" state.
2. **Direct redirect-to-product-page leaks.** Some signup paths (notably ones triggered
   from a deep-link or the docs) drop users on a product home page rather than
   `/onboarding/<product>?step=<...>`, so `onboarding started` never fires.

This is the **single largest addressable loss** — users who explicitly intended to start
PostHog (they clicked signup) and never even saw the onboarding scene.

### Drop-off B — onboarding started → first step completed (14,238 users / 30d)

32% of users who reach the onboarding scene don't progress past step 1. Hypotheses:

1. **Choice paralysis on `productSelection`** — multiple variants exist
   (`MultiproductProductSelection`, `SpotlightProductSelection`, `LegacyProductSelection`).
   Users may be uncertain which products to pick, especially if the use-case prompt
   didn't fire (`onboarding product selection path = use_case` rarely fires).
2. **Account/team scoping confusion** — invitees joining an existing org sometimes land
   on onboarding for a product that's already installed.

### Drop-off C — first step → first event ingested (10,939 users / 30d)

36% of users who advance past the first step never fire an event. Combined with the 73%
install-skip rate, this points squarely at the install step:

1. **Wrong SDK chosen** — the user picks Node.js but ships React, or picks `react-native`
   but ships Expo. Snippets fail silently.
2. **Snippet copy-paste failure / ad-blocker** — `onboarding adblock detection completed`
   fires with `status=blocked` for some users; this is observable per-user in PostHog.
3. **Tab abandonment** — user copies the snippet, leaves the tab to deploy, never
   returns. Even with async activation, ~36% never come back at all.

### Drop-off D — first event → onboarding completed (16,779 users / 30d)

86% of users with a first event don't click Finish. Hypothesis: this is mostly a
**measurement** problem rather than a UX problem. The flow doesn't force a return to
onboarding once the user is inside the product. Realistically:

- The user closes the install tab after seeing the snippet, the SDK fires async,
  `first team event ingested` lands while the user is offline, and they never see the
  verify state.
- Or the user reaches the verify state, then clicks into a dashboard tab and the
  onboarding tab is forgotten.

This is the worst step-over-step but the *least* addressable of the four. Better
measurement (treating "first event within 14d" as activation) and a server-driven
auto-complete-on-first-event would help — but this isn't where the experiment leverage is.

### Drop-off E — LLM-analytics-specific (33% first-event rate)

LLM analytics is **22 percentage points below** the baseline first-event rate. Likely
causes: most other products' SDKs install via a one-liner; LLM analytics requires
wrapping the model client (OpenAI / Anthropic / LangChain) and has more surface area for
copy-paste mistakes. Feature flags' 46% is similarly explainable — the install completes
when a flag is *evaluated*, not on SDK init.

## 4. Recommended experiments

Ranked by expected lift × tractability. **Primary success metric: 30d signup →
`first team event ingested` rate** (currently 26.6%). Treat `onboarding completed` as a
secondary because of the measurement problem above.

### Experiment 1 — "Continue your setup" interstitial (Drop-off A)

- **Hypothesis.** Signups that don't reach `/onboarding/...` mostly come from paths where
  the redirect target is wrong. Forcing a single interstitial after signup that says
  "Pick what you'd like to set up first" — with the same UI as `/onboarding` itself —
  will recover most of these users and make `onboarding started` near-universal post-signup.
- **Proposed change.** In `productSelectionLogic.ts`, when no `productKey` is set and the
  user just signed up (`is_organization_first_user=true`), force-redirect to
  `/onboarding` regardless of the URL the signup flow would otherwise have used.
  Add an opt-out link ("Skip and explore").
- **Success metric.** signup → `onboarding started` rate (currently 61%). Lift target: +20pp.
- **Expected primary-metric lift.** +5 to +8pp on activation (current 26.6% → 32-34%).
- **Implementation complexity.** **S**. Single redirect, feature-flag gated.

### Experiment 2 — Re-label and re-time the "Skip installation" button (Drop-off C)

- **Hypothesis.** "Skip installation" is misleading — most users who click it do install
  the SDK; they're just unwilling to wait for verification. Renaming to **"I'll verify
  later"** and surfacing a clearer "we'll auto-detect your first event" message will
  reduce anxiety and keep more users on the verify step long enough for the realtime
  check to land, raising the verified-install rate.
- **Proposed change.** In
  `frontend/src/scenes/onboarding/sdks/OnboardingInstallStep/NextButton.tsx`, change the
  unverified-state copy from "Skip installation" to "I'll verify later" and add a
  small inline indicator: "Most events arrive within 60 seconds — we'll auto-advance".
- **Success metric.** Ratio of `onboarding step completed{step_key=install}` /
  (`completed` + `skipped`) at that step. Currently 27%. Lift target: 27% → 45%.
- **Expected primary-metric lift.** +2 to +4pp on activation.
- **Implementation complexity.** **S**. Copy + one inline timer.

### Experiment 3 — Wizard-first install variant (Drop-off C)

- **Hypothesis.** Copy-paste installs are the failure mode. The wizard variants
  (`WizardOnlyVariant`, `WizardHeroVariant`) already exist in
  `frontend/src/scenes/onboarding/sdks/OnboardingInstallStep/variants/` but aren't the
  default for most SDKs. Defaulting to the wizard for frameworks where it works
  (Next.js, Nuxt, Astro) and falling back to snippets only when the wizard can't help
  will materially raise the verified-install rate, because the wizard runs the SDK init
  locally and verifies before the user touches the snippet.
- **Proposed change.** In the SDK install step's variant selector, switch the default
  from snippet variants to wizard variants for the frameworks where wizard support is
  shipped. Snippet fallback stays one click away for users on unsupported frameworks.
- **Success metric.** First-event rate within 30 minutes of starting the `install` step
  (use the `onboarding step completed` → `first team event ingested` median, currently
  ~35 min). Target: drop the median to ≤5 min.
- **Expected primary-metric lift.** +3 to +6pp on activation.
- **Implementation complexity.** **M**. Variant routing logic, but no new variant code.

### Experiment 4 — Targeted LLM-analytics onboarding (Drop-off E)

- **Hypothesis.** LLM analytics has the lowest first-event rate (33%) because the
  install requires wrapping a model client. A guided "paste your OpenAI/Anthropic key
  and we'll show you a trace right now" variant — analogous to the data-warehouse
  wizard already shipped under `data-warehouse/DataWarehouseQueryVariant.tsx` — should
  let users verify activation without changing their own code.
- **Proposed change.** New variant in
  `frontend/src/scenes/onboarding/sdks/ai-observability/AIObservabilitySDKInstructions.tsx`
  that prompts for a provider key and runs a single LLM call server-side, surfacing the
  trace inline. Original snippet-based instructions remain as the alternative.
- **Success metric.** `first team event ingested` rate for `product_key=llm_analytics`
  (currently 33%). Target: 33% → 50% (baseline parity).
- **Expected primary-metric lift.** +0.5pp on the project-wide activation rate (LLM
  analytics is only ~5% of starts), but a >50% relative lift for this product. Worth it
  because LLM analytics is a strategic-growth surface.
- **Implementation complexity.** **L**. Server endpoint, key handling, trace plumbing.

### Experiment 5 — Async activation handoff (Drop-off D)

- **Hypothesis.** The 86% drop from "first event" to "Finish clicked" is a measurement
  problem more than a UX problem, but it means we lose the chance to invite teammates,
  flip the activation flag server-side, and show the post-onboarding modal for most
  users. Server-side auto-completing onboarding when `first team event ingested` lands
  for a team that's still in onboarding would recover that.
- **Proposed change.** Backend listener on `first team event ingested` flips
  `has_completed_onboarding_for[productKey]=true` if the team is still in onboarding,
  and fires `onboarding completed` as a system-attributed event. Frontend continues
  to fire its own event when the user clicks Finish so the two paths don't conflict.
  Re-define the activation metric to **"first event within 14d"** in dashboards.
- **Success metric.** Defined as a measurement upgrade, not a UX lift. Validate by
  comparing the new server-driven `onboarding completed` rate to the existing one and
  checking that downstream retention curves match.
- **Expected primary-metric lift.** No direct lift on the existing 26.6% number, but
  cleans up reporting and makes future experiments measurable.
- **Implementation complexity.** **M**. Backend listener + admin-only flag rollout.

## 5. Data we tried to get and couldn't

- **Per-step time-on-page**: no per-step `step viewed` event with a timestamp delta is
  fired, so we can't tell whether users abandon `install` because they paused to deploy
  vs because they were confused. Worth adding a `onboarding step viewed` event in a
  follow-up.
- **Cohort comparison (activated vs not, first-session behaviour)**: this requires
  joining person properties to event sequences inside a 30-day window. The MCP
  `query-paths` tool would help but produces a wide tree; we'd want to write this as
  a HogQL `execute-sql` query against `system.persons` joined to events. Not done here
  because the funnel above already pinpoints the actionable losses.
- **Adblock-blocked users specifically**: `onboarding adblock detection completed` with
  `status=blocked` is in the data, but we didn't slice the funnel by it. Worth checking
  whether the install-skip rate is meaningfully higher in this segment as a follow-up.
- **`onboarding exit modal opened` segmented by step**: only ~3 events in 30d had a
  non-null `step_at_open` property (most were null), so we can't yet use the exit modal
  to localise drop-offs. The property may have been added recently — re-check in 60d.

## 6. Methodology notes

- All counts are unique users in the funnel unless explicitly noted.
- Date window: 2026-04-29 to 2026-05-29 (last 30 days), test accounts filtered.
- Conversion window: 14 days from signup (default funnel window). The mean conversion
  time for `signup → onboarding completed` is ~24 hours of total elapsed time, so a
  14d window captures the vast majority of completing users.
- The MCP `query-funnel` tool with `output_format: optimized` was used for the headline
  numbers; raw JSON was inspected for step-by-step counts.
- All saved query URLs are available in the MCP responses for reproduction.
