# Build a product alert frontend

Use this reference when adding or extending the alert editor, destinations, advanced settings, or evaluation history for a product.

Read `frontend/src/AGENTS.md` before changing frontend code. Keep business logic in keyed kea logic and use `kea-forms` for persisted alert forms. Network-backed actions need loading and double-submit protection.

## Choose the frontend path

Use `AlertWizard` from `frontend/src/lib/components/Alerting/AlertWizard/` when the product is creating HogFunction-backed alerts from trigger and destination templates.

Use the shared product alert editor components in `products/alerts/frontend/components/` when the product owns an alert configuration model, evaluation rules, lifecycle state, and history. Logs and insight alerts are the reference adopters.

A product can use both paths when it has a simple HogFunction creation flow and a richer product-owned alert configuration surface.

## Compose the shared editor

Build the product form around these components:

| Component                                          | Purpose                                                                                   | Product responsibility                                                                                       |
| -------------------------------------------------- | ----------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| `AlertEditor`                                      | Header, content, submit footer, loading, and changed-state behavior                       | Form logic, title, back/delete actions, and submit listener                                                  |
| `AlertEditorFormDetails`                           | Shared name, enabled state, and activity row                                              | Form field names and product activity content                                                                |
| `AlertEditorSection`                               | Consistent section title, description, and spacing                                        | Section content                                                                                              |
| `AlertDefinitionRow`                               | Definition row layout                                                                     | Source/filter pickers, mode controls, validation, normalized condition values, and product-specific previews |
| `AlertNextEvaluationStatus`, `AlertTimezoneNotice` | Next-run state and timezone presentation                                                  | Cadence controls, evaluated window, scheduling state, and settings URL                                       |
| `AlertAdvancedOptions`                             | Collapsible advanced-options shell and enabled-count badge                                | Product-specific fields and enabled-count calculation                                                        |
| `AlertNotificationDestinationEditor`               | Existing and pending destination rows, Slack picker, URL input, and add/remove actions    | Destination view models, supported destination types, payload construction, and persistence                  |
| `AlertEvaluationHistoryChart`                      | Generic evaluation plot, current thresholds, historical firing state, and truncation copy | Normalized points, threshold adapters, totals, and the product history table                                 |

Do not add product branches to these components. Normalize product data before rendering and keep product API calls, payloads, and state in the product adapter.

## Definition adapters

Keep definition primitives small and composable. Products should normalize common concepts without forcing unrelated evaluators into one schema:

- Render product source selectors or filters inside shared definition rows.
- Render threshold modes directly with `LemonSegmentedButton` while keeping options and validation in product logic.
- Map upper and lower bounds to product form fields. A product with a single comparator can expose one bound.
- Keep anomaly detector configuration, insight series/funnel/SQL fields, logs filters, and simulation results product-owned.
- Render cadence controls directly with existing Lemon components. Use `AlertNextEvaluationStatus` and `AlertTimezoneNotice` for shared presentation, while keeping cadence eligibility, entitlements, and due-time calculation product-owned.

Avoid a giant generic definition component with optional props for every product. Prefer shared layout primitives plus typed product adapters. Do not create pass-through wrappers around Lemon components or layout-only `div` elements.

## Destination adapters

`AlertNotificationDestinationEditor` renders normalized view models. The product still owns:

- Which destination types are allowed.
- How a pending destination becomes HogFunction input.
- How saved HogFunctions are grouped. Logs groups firing, resolved, and broken functions into one destination row.
- Detail URLs, labels, enabled state, deletion, and loading state.
- Email recipients or other product-specific notification controls outside the destination editor.

Reuse shared destination constants and backend builders where applicable, but do not assume every product supports every shared destination type.

## Evaluation history adapters

Map product history into `AlertEvaluationHistoryPoint`:

- `label`: formatted evaluation timestamp.
- `value`: evaluated numeric value, count, score, or probability.
- `firedAtTime`: whether that evaluation had the alert in a firing state at the time.

Map current product rules into `AlertEvaluationThreshold` with a direction, value, and display label. Keep the product table or event timeline beside the chart because history detail columns and pagination remain domain-specific.

Do not infer historical firing solely from the current threshold when persisted state exists. The chart distinguishes evaluations that fired at the time from evaluations that would fire under the current configuration.

## Advanced options

Use `AlertAdvancedOptions` for the shared collapse behavior. Calculate `enabledCount` from non-default product options.

Keep the fields product-owned. Insight alerts use ongoing-period checks, weekend skipping, and quiet hours. Logs alerts use N-of-M noise reduction and notification cooldown. Share a field only after a second adopter has the same input contract and semantics.

## Form and state rules

- Put listeners, reducers, selectors, loaders, and API calls in keyed kea logic.
- Bind product logic with `BindLogic` when multiple alerts can render simultaneously.
- Use `Form` and `LemonField` for persisted fields.
- Pass `isSubmitting`, `hasChanges`, and product pending changes into `AlertEditor`.
- Flush pending destinations only after the alert exists, and preserve failed pending destinations for retry.
- Keep container sizing in the product surface. Shared editor components must remain modal, scene, and embedded-section agnostic.

## Storybook and verification

Add or update stories for reusable shared components and product adapters.

- Use real background tokens such as `bg-bg-primary` or `bg-surface-primary`; `bg-default` is a legacy text-color alias and paints a dark background in light mode.
- Keep modal dimensions and borders in modal stories, not shared editor components.
- Cover loading, disabled submit, pending destinations, existing destinations, threshold modes, and history points where they represent realistic regressions.

Before finishing:

1. Run targeted Oxfmt and Oxlint on changed files.
2. Run `pnpm --filter=@posthog/frontend typescript:check` and separate changed-file failures from unrelated repository failures.
3. Run the lowest-level relevant Jest or Storybook tests when behavior changed.
4. Invoke `/writing-tests` before adding or substantially changing tests and `/writing-kea-logics` before changing product alert logic.
