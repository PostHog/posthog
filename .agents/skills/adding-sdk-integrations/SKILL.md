---
name: adding-sdk-integrations
description: >
  How to surface a PostHog SDK inside the PostHog app: the SDK setup picker in project settings, per-product onboarding install steps, and the backend `$lib` lists that decide whether the SDK's traffic is recognised.
  Use when adding a new SDK, extending an existing one to another product (session replay, feature flags, experiments, web analytics, surveys, logs, error tracking), or when an SDK is "already added" but does not appear in a picker.
  Covers the two independent pickers, the `docs/onboarding` step components, the integration points that fail silently because nothing renders them, the posthog.com and wizard repos, and how to verify snippets against the real SDK.
  Treat the file list here as a checklist to check against the tree, not a spec — rediscover it with the trace command below and update this skill when it drifts.
---

# Adding SDK integrations

An SDK reaches customers through two independent surfaces that do **not** share a list:

1. **SDK setup** in project settings — built from `SDK_CONFIGS` in
   [frontend/src/scenes/settings/environment/SDKSetupInstructions.tsx](../../../frontend/src/scenes/settings/environment/SDKSetupInstructions.tsx).
   `ProxySDKSetup.tsx` reuses it, so one entry covers both.
2. **Onboarding** — built from `ALL_SDKS` intersected with a per-product instructions map.
   An SDK in `ALL_SDKS` with no map entry is invisible for that product.

Adding the enum key and the catalogue entry is the half that looks finished and isn't. That is the usual bug: the SDK exists in the type system, and every picker is still empty.

## Two traps

**`legacy/` is the live default, not dead code.** The onboarding maps live under
`frontend/src/scenes/onboarding/legacy/sdks/`. `DEFAULT_VARIANT` in
[onboardingVariants.ts](../../../frontend/src/scenes/onboarding/onboardingVariants.ts) is `'legacy'`, so this is what most customers see. Skipping it because of the directory name ships an SDK nobody can select.

**`legacy/sdks/sdk-install-instructions/` really is dead.** Nothing outside that directory imports it. Do not add a file there. Confirm before trusting this:

```bash
rg -l "sdk-install-instructions" frontend/src products --glob '!**/sdk-install-instructions/**'
```

## Verify against the tree first

This list drifts. Before following it, trace an SDK that is already wired into every product and diff that against what you are adding:

```bash
# Flutter is wired end-to-end; android/ios/react-native work too
git grep -il "flutter" origin/master -- ':!*.lock' ':!*.ambr' ':!**/generated/**' ':!*.md'
```

Read the hits rather than pattern-matching the paths. Two known collisions: **Flutterwave** (a data warehouse source) is unrelated, and so is anything under `products/warehouse_sources/`.

## Tier 1 — required, or the SDK does not appear at all

| File                                                                    | Change                                                                                      |
| ----------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| `frontend/src/types.ts`                                                 | `SDKKey` enum entry                                                                         |
| `frontend/src/scenes/onboarding/legacy/sdks/allSDKs.tsx`                | catalogue entry: `name`, `key`, `tags: SDKTag[]`, `image`, `docsLink`                       |
| `frontend/src/scenes/onboarding/shared/logos/<sdk>.svg`                 | logo, unless `image` points at a Cloudinary URL (KMP does this — no asset needed)           |
| `docs/onboarding/product-analytics/<sdk>.tsx`                           | `get<Sdk>Steps(ctx)` + `export const <Sdk>Installation = createInstallation(get<Sdk>Steps)` |
| `docs/onboarding/product-analytics/index.ts`                            | barrel export                                                                               |
| `frontend/src/scenes/settings/environment/SDKSetupInstructions.tsx`     | `SDK_CONFIGS` entry: `Installation`, `name`, `docsLink`, `category`                         |
| `.../legacy/sdks/product-analytics/ProductAnalyticsSDKInstructions.tsx` | wrapper (`withMobileReplay` or `withOnboardingDocsWrapper`) + map entry                     |

## Tier 2 — one set per product you support

For each of session replay, feature flags, experiments, web analytics, surveys, logs, error tracking, workflows:

- `docs/onboarding/<product>/<sdk>.tsx`
- `docs/onboarding/<product>/index.ts` — barrel export
- `.../legacy/sdks/<product>/<Product>SDKInstructions.tsx` — wrapper + map entry

Only add products the SDK actually supports. Claiming one it doesn't is worse than omitting it.

Conventions worth copying rather than inventing:

- Feature flags, experiments and web analytics compose off the product-analytics steps. Session replay does **not** — every mobile SDK there is standalone.
- Composition selects a step by its **display title**, e.g. `.filter((step) => step.title !== 'Send events')`. A miss is silent, so keep your product-analytics step titles identical to the SDK you copied from. `frontend/src/scenes/onboarding/stepComposition.test.ts` guards this if present.
- Surveys prefixes its export: `Surveys<Sdk>Installation`.
- Mobile SDKs want a `case` in `legacy/sdks/session-replay/AdvertiseMobileReplay.tsx`, which otherwise falls back to "Mobile".
- `ctx` supplies `CodeBlock`, `Markdown`, `CalloutBox`, `Tab`, `dedent`, `snippets`. `Tab.Group tabs={[...]}` renders the tab bar itself; `Tab.List` is an inert website-compat shim.

## Tier 3 — the ones that get forgotten

Nothing renders these, so skipping them fails silently in production rather than in review.

**Backend `$lib` lists.** All keyed on the string the SDK reports. Check what the SDK actually sends — a wrapper SDK may override `$lib` on every platform, so it will not match the SDK it delegates to.

- [posthog/api/utils.py](../../../posthog/api/utils.py) — mobile-client check in `on_permitted_recording_domain`. Miss it and session recording is rejected for teams with authorized domains set.
- [posthog/models/team/production_event_activation.py](../../../posthog/models/team/production_event_activation.py) — `MOBILE_SIDE_LIBS` / `SERVER_SIDE_LIBS`
- `posthog/tasks/usage_report.py` + `posthog/temporal/usage_report/queries.py` — per-lib event and exception counters. **Regenerates `posthog/tasks/test/__snapshots__/test_usage_report.ambr`**, and moves billing counters, so this is often its own PR.
- `products/feature_flags/backend/flag_analytics.py`
- `nodejs/src/common/utils/utils.ts`
- `rust/feature-flags/src/utils/user_agent.rs` — user agent to lib name and `RuntimeType`

**SDK health and versions:** `products/growth/backend/{constants.py,sdk_health.py}`, `products/growth/dags/github_sdk_versions.py`, `frontend/src/scenes/onboarding/shared/sdkHealth/sdkConstants.ts`.

**Error tracking runtime:** `frontend/src/lib/components/Errors/{types.ts,utils.ts,displayOrder.ts}`, `products/error_tracking/frontend/components/RuntimeIcon.tsx`, and the hardcoded tile list in `products/error_tracking/frontend/components/SetupPrompt/SetupPrompt.tsx`. Add to `rust/cymbal/src/modes/processing/normalization.rs` only if stack frames need flipping.

**Feature flag and experiment detail pages** keep their own lists, separate from onboarding: `frontend/src/scenes/feature-flags/{FeatureFlagCodeOptions,FeatureFlagSnippets}.tsx`, `frontend/src/scenes/experiments/{ExperimentImplementationDetails,ExperimentCodeSnippets}.tsx`.

**Capability matrices:** `frontend/src/lib/components/SupportedPlatforms/{types.ts,SupportedPlatforms.tsx,featureSupport.tsx}`. For surveys also `frontend/src/scenes/surveys/surveyVersionRequirements.ts` and `frontend/bin/docs/build-survey-sdk-docs.ts`.

**Icons:** `frontend/src/lib/lemon-ui/icons/categories.ts`, `frontend/src/lib/integrations/GitHubIntegrationHelpers.tsx`.

**AI setup wizard:** if [PostHog/wizard](https://github.com/PostHog/wizard) has a `src/frameworks/<sdk>/` directory, set `wizardIntegrationName` on the `SDK_CONFIGS` entry. That renders the "Run the following command from the root of your X project" banner above the manual steps. It is display text only, so it does not have to match the wizard's framework id — but do not set it when the wizard cannot handle the SDK.

## Other repos

Two repos have to change too. Their file lists are not reproduced here, because this skill cannot verify them and a stale list is worse than a pointer — read the tree when you get there.

**[PostHog/posthog.com](https://github.com/PostHog/posthog.com) — required.** Every `docsLink` in this repo points at it, so shipping the app wiring without the docs page gives customers a 404 from the picker. Trace an existing SDK with `git grep -Il "flutter" -- '*.ts' '*.tsx' '*.mdx' '*.js'`. As of writing that is five places: the page at `contents/docs/libraries/<sdk>/index.mdx` (whose frontmatter `features` block drives the support matrices), a `platformLogo` entry in `src/constants/logos.ts`, an entry in `src/constants/installation-taxonomy.ts`, the sidebar in `src/navs/index.js`, and the grid in `src/components/Docs/Integrate.tsx`.

**[PostHog/wizard](https://github.com/PostHog/wizard) — optional.** A framework under `src/frameworks/<sdk>/` plus a `SkillId` entry lets the AI setup wizard install the SDK. Only then set `wizardIntegrationName` here, or the banner promises something the wizard cannot do.

The SDK's own repo is out of scope for this skill.

## Known dead ends

Confirm before relying on these; both were true when this skill was written.

- `legacy/sdks/sdk-install-instructions/` — unimported, see above.
- `SDK_KEY_TO_SNIPPET_LANGUAGE` in `frontend/src/lib/constants.tsx` — zero consumers.
- `legacy/sdks/skillBadge.tsx`, including `WIZARD_SKILL_IDS` and `WIZARD_SKILL_TO_SDK_KEY` — nothing imports the module. Use `wizardIntegrationName` instead, above.

## Verify the snippets, do not trust the docs page

Onboarding snippets are copied into real projects, so a wrong one costs a customer an afternoon.

For a compiled SDK (Kotlin, Swift, Java, C#), paste each snippet into a scratch source file in the SDK repo and build it against every target the snippet claims to support. Delete the scratch files afterward. Check the check has teeth by breaking one parameter name and confirming the build fails.

Compiling is necessary and not sufficient. It cannot catch a call that compiles everywhere and **throws on one platform** — the KMP SDK's no-argument `PostHogContext()` throws on Android, so a snippet using it compiled cleanly and crashed on launch. Read the platform-specific implementation of anything a snippet calls.

Also check defaults rather than repeating the marketing line. "PostHog automatically captures events" is false for an SDK that defaults `autocapture` and `captureScreenViews` to `false`.

## Verify the wiring

Add a test that asserts the SDK is selectable in every product you wired plus the settings picker. It catches an entry added to one map and forgotten in another, which is the failure mode here.

```ts
it.each(productsSupportingSdk)('makes <Sdk> selectable in %s onboarding', (_product, instructions) => {
    const sdk = getAvailableSDKs(instructions, {}, {}).find(({ key }) => key === SDKKey.<SDK>)
    expect(instructions[SDKKey.<SDK>]).not.toBeUndefined()
    expect(sdk).toMatchObject({ key: SDKKey.<SDK>, docsLink: DOCS_LINK })
})
```

Then assert `SDK_CONFIGS[SDKKey.<SDK>]` matches the name, docsLink and category. `ErrorTrackingSDKInstructions.test.ts` in the same directory is the closest existing example.

`docs/onboarding` is not a jest root, so tests that read those files live under `frontend/src`.

## Keep this skill current

These integration points move. When you add an SDK and find a file this skill does not list, or find a listed one gone or newly dead, update this skill in the same PR and say so in the description. A checklist that silently rots is worse than no checklist, because the next person trusts it.
