---
name: setting-feature-flags-in-storybook
description: 'Use when writing a Storybook story for a component gated on a feature flag — boolean flags or multivariate/experiment-arm variants. Covers the `featureFlags` story parameter and why imperatively setting flags renders the flag-off branch in visual-regression snapshots while passing in jest.'
---

# Setting feature flags in Storybook

> [!WARNING]
> Never call `featureFlagLogic.actions.setFeatureFlags(...)` from a story. It silently
> no-ops in the visual-regression runtime (rendering the flag-OFF branch) while passing
> in jest — so unit tests stay green and the snapshot is wrong. Use the `featureFlags`
> **story parameter** instead.

**Mental model:** boolean flags always work (they ride the always-merged baseline);
variant values need a gate that _only the `featureFlags` parameter opens correctly_.

## How to use it

This is the stable contract — prefer it over anything in "Under the hood" below.

### Boolean flags (flag is simply on)

```ts
const meta: Meta = {
  title: 'Scenes/MyScene',
  parameters: {
    featureFlags: [FEATURE_FLAGS.MY_FLAG, FEATURE_FLAGS.OTHER_FLAG],
  },
}
```

Array entries are flags that evaluate to `true`. This is the common case.

### Multivariate flags (pin a specific variant)

For a flag whose value is a variant string (experiment arms, multivariate rollouts), use
the **record form** — the array form can only express `true`:

```ts
// meta-level: applies to every story in the file
parameters: { featureFlags: { [FEATURE_FLAGS.THEME_OVERRIDE]: 'intent_plus' } }

// per-story: a different arm per story
export const ControlArm: Story = {
    parameters: { featureFlags: { [FEATURE_FLAGS.THEME_OVERRIDE]: 'control' } },
}
export const TreatmentArm: Story = {
    parameters: { featureFlags: { [FEATURE_FLAGS.THEME_OVERRIDE]: 'intent_plus' } },
}
```

You can mix booleans and variants in one record: `{ 'some-bool-flag': true, 'my-experiment': 'test_b' }`.

> [!IMPORTANT]
> A story's `parameters` **replace** the meta's (shallow merge), so a per-story
> `featureFlags` drops every flag set at the meta level. **Re-list any meta flags you
> still need** — silently losing one renders the flag-off branch and is easy to miss.

## Why the obvious approach fails

Setting flags imperatively (`featureFlagLogic.actions.setFeatureFlags`) works in `jest`
(`NODE_ENV==='test'`) but not in the built visual-regression Storybook. posthog-js loads
flags and fires `onFeatureFlags` with an empty set, which dispatches `setFeatureFlags`
and **wipes** whatever you set imperatively — so the unit test passes while the snapshot
renders the flag-OFF branch. The `featureFlags` parameter avoids this by writing flags to
the always-merged baseline instead (below), so the empty callback can't clobber them.

> Do **not** try to fix this by disabling posthog-js flags (e.g. `advanced_disable_feature_flags`).
> The app shell (`appLogic.showApp`) only renders once `receivedFeatureFlags` is true,
> which is set by that same `onFeatureFlags` callback — suppress it and every
> `Scenes-App/*` story stalls behind a 3s timeout and flakes.

## Under the hood (implementation detail — may drift)

> This explains _why_ the parameter works, for trust and for anyone extending the harness.
> Treat "How to use it" above as the contract, not this.

`withFeatureFlags` → `setFeatureFlags` (`frontend/src/mocks/browser.tsx`) writes the
flags (array or record) straight to `window.POSTHOG_APP_CONTEXT.persisted_feature_flags`.
`getPersistedFeatureFlags` (`frontend/src/lib/logic/featureFlagLogic.ts`) reads that as
`featureFlagLogic`'s initial value and `spyOnFeatureFlags` always merges it as the
baseline — so both booleans and pinned variants survive the empty `onFeatureFlags`
callback. The only production-side support this needs is `getPersistedFeatureFlags`
accepting the record form (variant values) in addition to the server's array form.

You should not need to touch any of this. If you're extending the harness, that's the seam.

## See also

The `featureFlags` parameter only controls the flag. If a component's render also depends
on other runtime state (localStorage, an `APP_CONTEXT` field, a kea logic that resolves an
entry), stage that state too — typically in a small wrapper the story renders that sets it
and mounts the logic before rendering the component. Keep that wrapper in the story file;
don't add test-only props to the production component to make it renderable.
