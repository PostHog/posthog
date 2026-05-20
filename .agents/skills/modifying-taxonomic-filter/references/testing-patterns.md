# Testing patterns for TaxonomicFilter

For boilerplate, copy from existing tests in
`frontend/src/lib/components/TaxonomicFilter/`. This doc only covers
the things that aren't obvious until they bite.

## Required setup (or tests fail silently)

**AutoSizer mock** — without this the virtualized list renders at zero
height and `getByTestId('prop-filter-…')` returns nothing while tests
appear to pass.

```tsx
jest.mock('lib/components/AutoSizer', () => ({
  AutoSizer: ({ renderProp }: { renderProp: (info: { height: number; width: number }) => JSX.Element }) =>
    renderProp({ height: 400, width: 400 }),
}))
```

**Search-aware mock handlers** — a static handler hides search-filtering
bugs. Always read the `search` param:

```tsx
'/api/projects/:team_id/event_definitions': (req) => {
    const search = req.url.searchParams.get('search')
    const filtered = search ? mockEventDefinitions.filter(e => e.name.includes(search)) : mockEventDefinitions
    return [200, { results: filtered, count: filtered.length }]
}
```

**Persons properties live under `/api/environments/:team/`, not `/projects/`.**
Mount shared models in `beforeEach`:

```tsx
beforeEach(() => {
  initKeaTests()
  actionsModel.mount()
  groupsModel.mount()
})
```

## Test IDs

| Element      | Pattern                        |
| ------------ | ------------------------------ |
| Search input | `taxonomic-filter-searchfield` |
| Tab buttons  | `taxonomic-tab-{groupType}`    |
| List items   | `prop-filter-{type}-{index}`   |

Active tab assertion: `expect(tab).toHaveClass('LemonTag--primary')`.

## Logic-level integration tests

`taxonomicFilterLogic` spawns child `infiniteListLogic` per group type
— mount them all, then await `loadRemoteItemsSuccess` before asserting:

```tsx
const logic = taxonomicFilterLogic({ taxonomicFilterLogicKey: 'test', taxonomicGroupTypes, onChange: jest.fn() })
logic.mount()
for (const groupType of taxonomicGroupTypes) {
  infiniteListLogic({ ...logic.props, listGroupType: groupType }).mount()
}

for (const groupType of taxonomicGroupTypes) {
  await expectLogic(infiniteListLogic({ ...logic.props, listGroupType: groupType })).toDispatchActions([
    'loadRemoteItemsSuccess',
  ])
}
```

## Don't delete the property-promotion test

`email` and `url` searches must promote `$email` and `$current_url` to
position 0 (see Product reality in `SKILL.md`):

```tsx
await userEvent.type(searchField, 'url')
await waitFor(() => expect(screen.getByText('$current_url')).toBeInTheDocument())
```

`redistributeTopMatches` is a pure function — test in isolation with
parameterized cases.
