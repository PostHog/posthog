# Testing and stories

Use [writing-tests](../../writing-tests/SKILL.md) before changing coverage.
Name the regression the change could introduce, then choose the lowest test level that catches it.
Extend an existing test when possible; do not add transform and adapter suites for every chart.

## Choose the test level

- Test changed data conversion or formatting through an existing pure helper test.
- Test state transitions through the existing kea logic test.
- Render the component only when the regression concerns rendered content or interaction wiring.
  Do not mock `@posthog/quill-charts` to inspect props instead of testing the behavior.
- Use browser checks for behavior or appearance that jsdom cannot prove.

For insight integration tests, reuse [renderInsight and its interaction helpers](../../../../frontend/src/test/insight-testing/index.ts).
[TrendsLineChart.test.tsx](../../../../products/product_analytics/frontend/insights/trends/TrendsLineChart/TrendsLineChart.test.tsx) shows tooltip, legend, and persons-modal checks.
For other consumers, use your existing render helper and `getHogChart(container)`.
See the [package consumer testing guide](../../../../packages/quill/packages/charts/src/docs/TESTING.md#testing-code-that-uses-hog-charts) for jsdom setup and DOM accessors.
Preserve `data-attr` values that these helpers use.

## Stories and visual checks

Reuse the nearest story and add only cases that expose a relevant visual difference.
Do not create every display permutation.
[TrendsLineChart.stories.tsx](../../../../products/product_analytics/frontend/insights/trends/TrendsLineChart/TrendsLineChart.stories.tsx) shows a sized stage, cached insight fixtures, and `parameters.mockDate`.

- Give the chart container real dimensions and use deterministic data.
- Pin the date when relative dates or incomplete buckets affect the output.
- Wait for the chart to render before taking a screenshot; use the existing story's readiness pattern.
- Check the changed surface at wide and narrow scene widths, including about 520px.
- Check light and dark themes when colors or contrast change.

The [app theme builder](../../../../frontend/src/lib/charts/utils/theme.ts) supports `storybook-skip-chart-canvas` for snapshots that only need DOM overlays.
Do not use it to validate chart painting or hide a rendering regression.
