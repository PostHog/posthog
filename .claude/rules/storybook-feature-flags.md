---
paths:
  - 'frontend/src/**/*.stories.tsx'
  - 'products/*/frontend/**/*.stories.tsx'
---

If this story renders a component gated on a feature flag, set the flag via the
`featureFlags` story parameter — not by calling `featureFlagLogic.setFeatureFlags`
imperatively (that is silently dropped in the visual-regression runtime). For a
multivariate flag use the record form, e.g.
`parameters: { featureFlags: { [FEATURE_FLAGS.MY_FLAG]: 'test_b' } }`.
Invoke the `/setting-feature-flags-in-storybook` skill before making changes.
