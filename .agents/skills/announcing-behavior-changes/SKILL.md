---
name: announcing-behavior-changes
description: >
  Decides whether a behavior-changing fix needs an in-app notice, then builds one that reaches only the affected users and can be removed later.
  Use when a change alters what an existing user sees without them doing anything — a metric moves, a chart shifts, a count drops, a date range resolves differently, a matcher matches differently — and when adding, reviewing, or removing such a notice.
  Trigger terms: behavior change, breaking change, semantics change, "results may differ", change notice, deprecation banner, migration banner.
  Carries the gate (narrow to the affected users with a tested predicate, or do not ship a notice at all), the pattern from `SqlInsightDateFilterNotice`, where to anchor the notice, and the flag-based removal path.
  Not for new features (use the changelog), not for permanent per-object warnings computed by the backend, and not for the wording itself (see `/writing-user-facing-copy`).
---

# Announcing behavior changes

Some fixes correct wrong behavior but change what a user sees. The number moves, the chart shifts, the count drops. Nothing is broken, but from the user's side it is indistinguishable from a regression, and they have no way to find out why.

An in-app change notice closes that gap: it appears where the user sees the different result, says what changed, and then goes away.

The reference implementation is `frontend/src/queries/nodes/DataVisualization/Components/SqlInsightDateFilterNotice.tsx`, shipped in commit `76f2905222a` alongside the backend change it explains. Read it before writing a new one — it is 60 lines and it is the whole pattern.

## First: does this change need a notice?

Most changes do not. A notice that fires for people it does not concern is worse than no notice, because it teaches everyone to dismiss banners without reading them. Ship one only when all four hold.

1. **A user who does nothing sees something different.** Not a new feature, not a change they opted into behind a flag.
2. **They cannot work out why from the screen.** If the UI already explains it, the UI is the notice.
3. **The difference is big enough to notice.** A rounding change in the fourth decimal is not.
4. **You can identify who is affected, in code.** See below — this is the one that usually fails.

### The narrowing test

Write the predicate first. If you cannot express "this user is affected" as a function of state the client already has, you are about to show a banner to everyone about something that concerns a minority.

When that happens, pick a different mechanism instead of widening the blast radius:

| Situation                                                                   | Use instead                                                                                                                                                                    |
| --------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Only the backend can tell who is affected                                   | A per-object field on the API response, rendered where that object is shown. `Action.selector_warning` ([#80653](https://github.com/PostHog/posthog/pull/80653)) is the model. |
| The condition is permanent, not a one-time transition                       | Same — a computed warning, not a time-boxed notice.                                                                                                                            |
| Everyone is affected but the change is minor                                | Changelog only.                                                                                                                                                                |
| The old behavior was plainly broken and the new one is self-evidently right | Nothing. An error that stops happening needs no announcement.                                                                                                                  |

## The pattern

Five pieces. All of them ship in the **same PR as the behavior change**, so a reviewer sees the change and its explanation together, and the notice cannot be forgotten once the change is out.

### 1. An exported, tested predicate

Mirror the backend rule in a named function, and say in a comment which backend code it mirrors so the two can be kept honest.

```ts
/** Whether the SQL date filter resolution fix can produce different results for this query.
 * Mirrors the affected shapes of ReplaceFilters in posthog/hogql/filters.py. */
export function isAffectedByDateFilterResolutionChange(source: HogQLQuery): boolean {
```

Export it separately from the component so it can be unit tested without rendering.

### 2. A feature flag

Declare it in `frontend/src/lib/constants.tsx` with an owner comment, in the same style as the neighbours:

```ts
SQL_INSIGHT_DATE_FILTER_NOTICE: 'sql-insight-date-filter-notice', // owner: #team-product-analytics, gates the notice on SQL insights affected by the date filter resolution fix
```

The flag does three jobs: it lets you roll the notice out gradually, it lets you turn it off without a deploy if the copy is wrong or the predicate is too broad, and it is the handle you retire the notice by when it has served its purpose.

### 3. A component that returns `null` by default

Both gates, flag first — it is the cheaper check and the kill switch:

```tsx
export function SqlInsightDateFilterNotice({ source }: { source: HogQLQuery }): JSX.Element | null {
  const { featureFlags } = useValues(featureFlagLogic)

  if (!featureFlags[FEATURE_FLAGS.SQL_INSIGHT_DATE_FILTER_NOTICE] || !isAffectedByDateFilterResolutionChange(source)) {
    return null
  }

  return (
    <LemonBanner type="info" dismissKey="sql-insight-date-filter-notice">
      Date filters on SQL insights now match other insights: relative ranges start at midnight, and open-ended ranges
      include all of today but nothing after. Results may differ slightly from before.
    </LemonBanner>
  )
}
```

Use `LemonBanner` — do not hand-roll. `type="info"`, because nothing is wrong. `dismissKey` gives permanent per-user dismissal through `lemonBannerLogic`'s `persist: true` reducer, at no cost. Keep the key stable and equal to the flag key; changing it re-shows the notice to everyone who already dismissed it.

### 4. An anchor where the result appears

Render it next to the thing that looks different, not next to the control that changed. The exemplar sits above the visualization in `DataVisualization.tsx`, not on the date filter, because the chart is what the user is staring at.

Prefer one shared render site over many. A notice about relative date ranges placed in `frontend/src/lib/components/DateFilter/DateFilter.tsx` reaches insights, dashboards, web analytics, session replay, error tracking, and AI observability at once, because they all render that component.

### 5. A removal date

The exemplar is missing this, and it is the reason the repo still carries `WebAnalyticsFiltersV2MigrationBanner.tsx` (added January 2026, untouched since) and `SamplingDeprecationNotice.tsx`. Nobody deletes these.

Put the date in a comment above the component, and repeat it in the flag's description in PostHog so it is visible to whoever audits flags later:

```tsx
// Remove after 2026-11-01, once affected users have had a full quarter to see it.
```

Be aware of what this does and does not buy you. Turning the flag off kills the notice immediately and without a deploy, so the user-visible half of removal is solved. Deleting the code is not: **nothing in CI or in any scheduled job currently checks these dates**, and the repo has no automated stale-flag sweep. The date is a note to a human.

So take the last step yourself. When you turn the flag off, open the follow-up in the same sitting and delete the component, its test, the flag constant, and the render site together. `/cleaning-up-stale-feature-flags` helps find the flag once it has gone quiet, but it works against a PostHog project's flags, not against this repo's code — it will not tell you the component is still there.

If you are reading this because notices have piled up, that is the gap to close, and it is a better investment than adding features to the notices themselves.

## Writing the copy

Invoke `/writing-user-facing-copy` for the voice rules. The shape that works for this genre is two clauses: **what changed, concretely**, then **that results may differ**.

> Date filters on SQL insights now match other insights: relative ranges start at midnight, and open-ended ranges include all of today but nothing after. Results may differ slightly from before.

- Describe the new behavior in terms of what the user sees, not the internals. "Relative ranges start at midnight", not "`date_from` snaps via `relative_date_parse`".
- Say plainly that numbers may differ. That sentence is the whole point — it is what stops someone filing a bug.
- Do not apologize, and do not call it a fix or an improvement. Both editorialize, and "we fixed a bug" implies their old numbers were worthless, which is usually more alarming than the truth.
- Two sentences. If it needs more, link to docs.

## Testing

The predicate gets a parameterized unit test covering affected **and** unaffected cases — a wrong predicate means either silence for the people who needed telling, or a banner for everyone else. `SqlInsightDateFilterNotice.test.ts` is the model: `it.each` over `[name, input, expected]`, with comments grouping the cases by the rule they exercise.

Do not test the component's rendering. The flag check and `LemonBanner` are both already covered; per `/writing-tests`, that test catches no realistic regression.

## Checklist

- [ ] The four gate conditions hold, and the predicate narrows to the affected users
- [ ] Predicate exported, commented with the backend code it mirrors, and unit tested both ways
- [ ] Flag declared in `lib/constants.tsx` with an owner comment
- [ ] Component returns `null` unless flag and predicate both pass
- [ ] `LemonBanner type="info"` with a `dismissKey` equal to the flag key
- [ ] Anchored where the changed result appears, at the most shared render site available
- [ ] `// Remove after YYYY-MM-DD` comment above the component
- [ ] Shipped in the same PR as the behavior change it explains
