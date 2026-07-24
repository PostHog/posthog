# Reducer vs selector vs cache vs loader

Most kea bugs come from picking the wrong container for a piece of state. Use this
decision flow before you write a new field.

## Decision flow

1. **Does it come from an HTTP call?** Use a [loader](loading-data.md).
2. **Can it be computed from other state?** Use a `selector`.
3. **Does an action change it, and does the UI need to re-render when it changes?**
   Use a `reducer`.
4. **Is it a timer, listener, or other disposable resource?** Use `cache.disposables`
   — see [using-kea-disposables](../../using-kea-disposables/SKILL.md).

If none of the above fit and you need a transient, non-reactive flag the UI never
reads (a re-entry guard inside a listener, for example), then `cache.foo` is the
escape hatch. Reach for it last, not first — most "I need a flag" cases are actually
served by `fooLoading` from a loader or `isFooSubmitting` from a form. `cache.foo`
also has nothing to do with `cache.disposables` despite sharing the namespace — they
are separate concerns.

## Why this matters

- **Reducers are the only thing React subscribes to via `useValues`.** Putting
  reactive state in `cache` means components won't re-render when it changes.
- **Selectors are memoised.** A reducer that mirrors a computed value will drift
  out of sync the moment one of its inputs changes from somewhere else.
- **Loaders give you `xLoading` for free.** Building your own `isLoadingFoo` reducer
  duplicates state you already have.
- **`cache` is escape-hatch state**: re-entry guards, one-shot flags, debounce
  timers (when not using disposables). The UI must never depend on it.

## Patterns

### Action-driven state — reducer

```ts
reducers({
  name: ['' as string, { setName: (_, { name }) => name }],
  selectedIds: [
    [] as string[],
    {
      select: (state, { id }) => [...state, id],
      deselect: (state, { id }) => state.filter((x) => x !== id),
      clearSelection: () => [],
    },
  ],
})
```

A reducer **listens to actions and returns the next state**. Pure function, no side
effects. The default value is the first array element; handlers are the last.

### Derived state — selector

```ts
selectors({
  selectedCount: [(s) => [s.selectedIds], (selectedIds): number => selectedIds.length],
  isAllSelected: [
    (s) => [s.selectedIds, s.allIds],
    (selectedIds, allIds): boolean => selectedIds.length === allIds.length,
  ],
})
```

Selectors take an array of input selectors and a result function. Result is memoised
on identity of the inputs. Always annotate the return type — typegen needs it for
downstream consumers.

You can read another logic's selector inside a result function via `s.someValue` (if
connected) or `otherLogic.selectors.someValue` (when you'd rather not connect). The
connected form is preferred — type safety, explicit dependency declaration, and
nothing surprising at mount time.

### Transient flag — cache

```ts
listeners(({ values, actions, cache }) => ({
  submit: async () => {
    if (cache.submitting) return // re-entry guard
    cache.submitting = true
    try {
      await api.things.create(values.thing)
    } finally {
      cache.submitting = false
    }
  },
}))
```

`cache` is plain mutable state on the logic instance. No reducers, no actions, no
React subscription. Only use for things the UI doesn't render.

## Common mistakes

- **Reducer that duplicates a selector.** If `fullName` is always
  `firstName + ' ' + lastName`, it's a selector, not a reducer.
- **Selector that should be a reducer.** If the value is set by an action and not
  computed from anything else, it's a reducer.
- **Cache used for UI state.** No re-render will happen. The UI will look stale until
  some other action triggers a re-render coincidentally.
- **Mirroring loader data into a reducer.** Loaders already give you the value plus
  `xLoading`. Don't add a `foo` reducer alongside a `loadFoo` loader.
