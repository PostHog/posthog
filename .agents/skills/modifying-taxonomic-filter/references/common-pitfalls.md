# Common pitfalls when modifying TaxonomicFilter

Lessons learned from 8 PRs of incremental changes to this component.

## Always write tests before changing behavior

The single most important rule. The filter has subtle interdependencies —
changing one thing often breaks another in ways that only surface through
user-visible behavior.

**Workflow:**

1. Write RTL tests that lock down the current behavior you plan to touch
2. Verify the tests pass
3. Make your change
4. Verify both old and new tests pass

Skipping step 1 leads to regressions that are hard to diagnose because you
can't distinguish "my change broke this" from "this was already broken."

## Assertions that look right but don't catch regressions

### Checking existence instead of content

```tsx
// BAD: passes even if the wrong items are shown
expect(screen.getByTestId('prop-filter-events-0')).toBeInTheDocument()

// GOOD: verifies the actual content
expect(screen.getByTestId('prop-filter-events-0')).toHaveTextContent('$pageview')
```

### Not waiting for async updates

```tsx
// BAD: might pass because the old data hasn't been replaced yet
await userEvent.type(searchField, 'new query')
expect(screen.getByTestId('prop-filter-events-0')).toHaveTextContent('old result')

// GOOD: wait for the new data to arrive
await userEvent.type(searchField, 'new query')
await waitFor(() => {
  expect(screen.getByTestId('prop-filter-events-0')).toHaveTextContent('new result')
})
```

### Testing logic state instead of rendered output

```tsx
// BAD: tests the implementation, not the behavior
await expectLogic(logic).toMatchValues({ activeTab: 'events' })

// GOOD: tests what the user sees
expectActiveTab('events')
```

Use logic-level tests for internal invariants (e.g., `redistributeTopMatches`
output). Use component tests for anything the user interacts with.

## Group ordering stability

The tab order is driven by `taxonomicGroupTypes` prop and dynamic reordering
in `taxonomicFilterLogic`. Changes to ordering logic can break:

- **Keyboard navigation**: Tab/Shift+Tab cycles through visible tabs in order.
  If you change which tabs are visible or their order, keyboard navigation
  tests will fail.
- **Default active tab**: The first non-empty group becomes active. Reordering
  can change which tab the user sees first.
- **Shortcut group promotion**: When search matches a shortcut group type,
  it gets promoted after `SuggestedFilters`. Adding or removing shortcut
  types changes the promoted order.

**Safe approach:** If you need to change group ordering, write a parameterized
test covering all the ordering scenarios before changing the logic.

## Error handling for API failures

Each `infiniteListLogic` fetches data independently. A failure in one tab
should not break other tabs. When modifying fetch logic:

- Ensure `loadRemoteItemsFailure` is handled gracefully (empty results, not crash)
- Test that other tabs still work when one tab's API returns an error
- The `SuggestedFilters` tab aggregates from all tabs — it should handle
  partial failures (some tabs succeed, some fail)

## Keyboard navigation edge cases

The keyboard handler in `TaxonomicFilter.tsx` handles:

- ArrowUp/ArrowDown: navigate within the current list
- Tab/Shift+Tab: switch between tabs
- Enter: select the highlighted item
- Escape: close the filter

Common mistakes:

- **Not testing empty states**: ArrowDown in an empty list should be a no-op,
  not throw an error
- **Focus management**: After Tab switches tabs, focus should stay in the
  search input, not jump to the list
- **Tab wrapping**: Tab on the last tab should wrap to the first tab
  (and vice versa for Shift+Tab)

## The AutoSizer mock is required

`InfiniteList` uses `AutoSizer` from `react-virtualized-auto-sizer`.
Without the mock, the component renders with zero height and no items
are visible. Every component test file must include the mock. If you
create a new test file for a sub-component, you'll need it there too.

## Search-aware mock handlers

When testing search behavior, your API mocks need to respect the search
query parameter. A static mock that always returns the same results
won't catch bugs in search filtering:

```tsx
// BAD: always returns the same results regardless of search
'/api/projects/:team/event_definitions': mockEventDefinitions

// GOOD: filters based on search parameter
'/api/projects/:team/event_definitions': (req) => {
'/api/projects/:team_id/event_definitions': (req) => {
    const search = req.url.searchParams.get('search')
    const filtered = search
        ? mockEventDefinitions.filter(e => e.name.includes(search))
        : mockEventDefinitions
    return [200, { results: filtered, count: filtered.length }]
}
```

## SuggestedFilters and top matches

The `SuggestedFilters` group is special — it aggregates results from all
other groups. When modifying it:

- `redistributeTopMatches` is a pure function. Test it in isolation with
  parameterized tests covering edge cases (empty groups, uneven distribution,
  groups at the max limit).
- Skeleton rows (`SKELETON_ROWS_PER_GROUP = 3`) show while data loads.
  Test that skeletons appear before results and disappear after.
- `appendTopMatches` collects items as each tab's results arrive. The
  order items appear depends on which API responds first — don't assert
  on order within the suggested filters tab unless you control the
  response timing.

## Modifying the TaxonomicFilterGroupType enum

Adding a new group type touches many places:

1. The `TaxonomicFilterGroupType` enum in `types.ts`
2. Group configuration in `taxonomicFilterLogic.tsx` (the `groups` selector)
3. Potentially `SHORTCUT_TO_PROPERTY_FILTER_GROUP_TYPES` if it's a shortcut type
4. API endpoint configuration for the new type's data source
5. Every place that switches on group type (rendering, icons, labels)

**Safe approach:** Search for an existing similar group type and follow the
same pattern. Add RTL tests for the new tab before wiring it up.

## Don't test `taxonomicFilterLogic` selectors by re-implementing them

The logic has complex derived selectors (e.g., `infiniteListCounts`,
`redistributedTopMatchItems`). Don't duplicate the computation logic in
your test to build expected values. Instead:

- Test the pure functions directly with known inputs/outputs
- Test selectors through their observable effects (what renders, what
  actions fire)
- Use `.toMatchValues()` with `expect.objectContaining()` for partial
  checks rather than exact matches on complex objects
