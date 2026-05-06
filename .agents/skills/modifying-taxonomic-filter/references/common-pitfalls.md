# Common pitfalls when modifying TaxonomicFilter

Generic engineering rules don't earn space here. This is the
component-specific traps.

## "If you change X, also check Y"

| Change                                             | Verify                                                                                                                                                     |
| -------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Tab ordering or visibility                         | Keyboard nav (Tab cycles), default active tab, both `control` and `pill` dropdown variants, suggested-filters tab                                          |
| `PROMOTED_PROPERTIES_BY_SEARCH_TERM` or sort order | `$email` and `$current_url` still at position 0 for `email` / `url` searches                                                                               |
| Selectors feeding `topMatchesForQuery`             | Per-tab output **and** parent `appendTopMatches` aggregation; SuggestedFilters tab still populates                                                         |
| Search input or paste handling                     | `inputMode` field on `taxonomic_filter_search_query` still distinguishes typed/pasted/mixed                                                                |
| `selectItem` logic                                 | Telemetry payload (`sourceGroupType`, `wasFromRecents`, `wasFromPinnedList`, `wasQuickFilter`, `position`); recents still recorded; `onChange` still fires |
| Persistence keys (recents or pinned)               | Team-id prefix still applied; items don't leak across teams                                                                                                |
| Filter open/close lifecycle                        | `cache.openedAt` / `cache.hadSelection` still set; `taxonomic filter closed` still fires with `dwellMs` and `hadSelection`                                 |
| Adding a `TaxonomicFilterGroupType`                | Group config in `taxonomicFilterLogic.tsx`, shortcut routing, telemetry includes the new type, every consumer's `taxonomicGroupTypes` prop updated         |
| Reactive prop behavior in any logic                | Use `propsChanged` + `afterMount`, not subscriptions (see below)                                                                                           |

Suggested-filters items appear in API-response order; don't assert on
order within that tab unless you control the timing.

## `propsChanged` + `afterMount`, not subscriptions

```typescript
afterMount(({ actions, props }) => {
  if (props.eventNames?.length) actions.ensureLoadedForEvents(props.eventNames)
}),
propsChanged(({ actions, props }, oldProps) => {
  if (props.eventNames !== oldProps.eventNames && props.eventNames?.length) {
    actions.ensureLoadedForEvents(props.eventNames)
  }
}),
```

kea-subscriptions are slower and have re-mount cost. Established by
`perf(taxonomic-filter): replace eventNames subscription with propsChanged + afterMount`.
