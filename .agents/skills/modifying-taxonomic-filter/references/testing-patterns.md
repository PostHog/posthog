# Testing patterns for TaxonomicFilter

## RTL test setup

Every component test needs these pieces:

### AutoSizer mock

The virtualized list uses `AutoSizer` which needs a browser layout engine.
Mock it to render children with fixed dimensions:

```tsx
jest.mock('lib/components/AutoSizer', () => ({
  AutoSizer: ({ renderProp }: { renderProp: (info: { height: number; width: number }) => JSX.Element }) =>
    renderProp({ height: 400, width: 400 }),
}))
```

### API mocks with `useMocks()`

Set up before each test. The filter fetches event definitions, property definitions, actions, and persons:

```tsx
useMocks({
  get: {
    // Event and property definitions live under /api/projects/:team/...
    '/api/projects/:team/event_definitions': mockGetEventDefinitions,
    '/api/projects/:team/property_definitions': mockGetPropertyDefinitions,
    '/api/projects/:team/actions': mockGetActions,
    // Person properties are fetched from /api/environments/:team/...
    '/api/environments/:team/persons/properties': mockGetPersonsProperties,
  },
  post: {
    // Queries are posted to the environments endpoint
    '/api/environments/:team/query': [200, { results: [] }],
  },
})
```

### Kea initialization

Mount shared models before each test:

```tsx
beforeEach(() => {
  initKeaTests()
  actionsModel.mount()
  groupsModel.mount()
})
```

### The `renderFilter()` helper

Wrap the component in a kea `<Provider>` with sensible defaults:

```tsx
const renderFilter = (props: Partial<TaxonomicFilterProps> = {}): RenderResult => {
  return render(
    <Provider>
      <TaxonomicFilter
        taxonomicFilterLogicKey="test-filter"
        taxonomicGroupTypes={[
          TaxonomicFilterGroupType.Events,
          TaxonomicFilterGroupType.Actions,
          TaxonomicFilterGroupType.PersonProperties,
        ]}
        onChange={jest.fn()}
        {...props}
      />
    </Provider>
  )
}
```

## Component-level test patterns

### Test IDs to query

| Element      | Test ID pattern                | Example                                              |
| ------------ | ------------------------------ | ---------------------------------------------------- |
| Search input | `taxonomic-filter-searchfield` | `screen.getByTestId('taxonomic-filter-searchfield')` |
| Tab buttons  | `taxonomic-tab-{groupType}`    | `screen.getByTestId('taxonomic-tab-events')`         |
| List items   | `prop-filter-{type}-{index}`   | `screen.getByTestId('prop-filter-events-0')`         |

### Asserting the active tab

```tsx
const expectActiveTab = (type: string): void => {
  const tab = screen.getByTestId(`taxonomic-tab-${type}`)
  expect(tab).toHaveClass('LemonTag--primary')
}
```

### Typing in search

```tsx
const searchField = screen.getByTestId('taxonomic-filter-searchfield')
await userEvent.type(searchField, 'pageview')
```

### Waiting for results after search

Search triggers API calls. Wait for the DOM to update:

```tsx
await waitFor(() => {
  expect(screen.getByTestId('prop-filter-events-0')).toBeInTheDocument()
})
```

### Switching tabs

```tsx
const actionsTab = screen.getByTestId('taxonomic-tab-actions')
await userEvent.click(actionsTab)
expectActiveTab('actions')
```

### Keyboard navigation

The filter handles ArrowUp, ArrowDown, Tab, Enter, and Escape.
Test keyboard flows end-to-end through the rendered component:

```tsx
await userEvent.keyboard('{ArrowDown}')
await userEvent.keyboard('{ArrowDown}')
await userEvent.keyboard('{Enter}')
expect(onChange).toHaveBeenCalledWith(/* expected group and value */)
```

### Item selection

```tsx
const onChange = jest.fn()
renderFilter({ onChange })

await waitFor(() => {
  expect(screen.getByTestId('prop-filter-events-0')).toBeInTheDocument()
})

await userEvent.click(screen.getByTestId('prop-filter-events-0'))
expect(onChange).toHaveBeenCalledWith(
  expect.objectContaining({ type: TaxonomicFilterGroupType.Events }),
  expect.anything(),
  expect.anything()
)
```

### Testing excluded properties

Pass `excludedProperties` and assert the excluded items do not appear:

```tsx
renderFilter({
  excludedProperties: { [TaxonomicFilterGroupType.PersonProperties]: ['location'] },
})

await waitFor(() => {
  expect(screen.queryByText('location')).not.toBeInTheDocument()
})
```

### Testing property promotion

Certain search terms promote specific properties (e.g., typing "url" promotes `$current_url`).
Search for the term, then assert the promoted property appears in the results:

```tsx
await userEvent.type(searchField, 'url')
await waitFor(() => {
  expect(screen.getByText('$current_url')).toBeInTheDocument()
})
```

## Logic-level test patterns

### Mounting the logic with all child logics

The orchestrator logic creates child `infiniteListLogic` instances.
Mount them all for integration-style tests:

```tsx
const logic = taxonomicFilterLogic({
  taxonomicFilterLogicKey: 'test',
  taxonomicGroupTypes: groupTypes,
  onChange: jest.fn(),
})
logic.mount()

for (const groupType of groupTypes) {
  infiniteListLogic({ ...logic.props, listGroupType: groupType }).mount()
}
```

### `expectLogic().toMatchValues()`

Assert computed values without triggering actions:

```tsx
await expectLogic(logic).toMatchValues({
  activeTab: TaxonomicFilterGroupType.Events,
  infiniteListCounts: expect.objectContaining({
    [TaxonomicFilterGroupType.Events]: expect.any(Number),
  }),
})
```

### `expectLogic(logic, () => action).toMatchValues()`

Trigger an action and assert the resulting state:

```tsx
await expectLogic(logic, () => {
  logic.actions.setSearchQuery('pageview')
}).toMatchValues({
  searchQuery: 'pageview',
})
```

### `toDispatchActions`

Assert that an action dispatches expected follow-up actions:

```tsx
await expectLogic(logic, () => {
  logic.actions.setSearchQuery('test')
}).toDispatchActions(['setSearchQuery'])
```

### Waiting for remote results

API calls are async. Use a helper that waits for the success action:

```tsx
const waitForRemoteResults = async (groupType: TaxonomicFilterGroupType): Promise<void> => {
  const listLogic = infiniteListLogic({ ...logic.props, listGroupType: groupType })
  await expectLogic(listLogic).toDispatchActions(['loadRemoteItemsSuccess'])
}
```

### Testing pure functions

Functions like `redistributeTopMatches` can be tested directly without kea.
Use parameterized tests with a helper to build test items:

```tsx
const makeItem = (groupType: TaxonomicFilterGroupType, count: number): TaxonomicDefinitionTypes[] =>
  Array.from({ length: count }, (_, i) => ({ name: `${groupType}-${i}` }))

it.each([
  {
    name: 'distributes evenly across groups',
    items: { Events: makeItem(Events, 10), Actions: makeItem(Actions, 10) },
    expected: { Events: 5, Actions: 5 },
  },
  // ... more cases
])('$name', ({ items, expected }) => {
  const result = redistributeTopMatches(items, groupTypes)
  // assert distribution
})
```

## Key testing principles

1. **Test behavior, not implementation** — assert what the user sees (text, elements, callbacks), not internal kea state
2. **Lock down existing behavior before changing it** — write RTL tests for current behavior first, then modify
3. **Prefer component tests over logic tests** for user-facing behavior — logic tests are for internal invariants
4. **Always wait for async results** — the filter fetches data on mount and on search; use `waitFor` or `waitForRemoteResults`
5. **Use `userEvent` not `fireEvent`** — `userEvent` simulates real browser behavior (focus, blur, keydown sequences)
