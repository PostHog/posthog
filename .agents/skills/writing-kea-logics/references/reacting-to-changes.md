# Reacting to changes

When a value changes, what should run? PostHog has a hierarchy. Try each option in
order — only fall through to the next when the previous can't express the case.

| Option                        | Use when                                               |
| ----------------------------- | ------------------------------------------------------ |
| Selector                      | The "reaction" is just a derived value.                |
| `listeners` on the action     | Something dispatches an action when the value changes. |
| `propsChanged`                | The value is a logic prop changing from React.         |
| `urlToAction` / `actionToUrl` | The value is URL state. See [routing.md](routing.md).  |
| `kea-subscriptions`           | Truly nothing above fits.                              |

Why the order: each option is cheaper and more predictable than the next. Subscriptions
re-run on every dispatch in the entire app — pay that cost only when you have to.

## Selectors — "react" by computing

If your "reaction" is just deriving a new value (a count, a formatted string, a
boolean), use a selector. The UI re-renders when the inputs change; there's no
imperative listener at all.

```ts
selectors({
  visibleItems: [(s) => [s.items, s.filter], (items, filter) => items.filter((i) => i.name.includes(filter))],
})
```

If you found yourself writing a listener that just does
`actions.setVisibleItems(items.filter(...))`, that's a selector instead.

## Listeners — react to an action

Use when the value change is the result of an action somebody dispatched.

```ts
listeners(({ actions, values }) => ({
    setFilter: ({ filter }) => {
        // filter changed via an action — react here
        actions.loadResults(filter)
    },
    loadResultsSuccess: () => {
        // an async action finished — react here
        actions.trackEvent('results_loaded', { count: values.results.length })
    },
})),
```

If the value lives in another logic, `connect` to its action and listen for it:

```ts
connect(() => ({ actions: [otherLogic, ['setX']] })),
listeners(({ actions }) => ({
    setX: ({ x }) => { /* react to other logic */ },
})),
```

## `propsChanged` — react to props

When a value comes from React props (the parent re-renders with new props), use
`propsChanged`:

```ts
propsChanged(({ actions, props }, oldProps) => {
  if (props.fooId !== oldProps.fooId) {
    actions.loadFoo()
  }
})
```

The second argument is the previous props. Always guard against
identity-but-not-value changes — React may re-render with structurally equal but
referentially different props.

## Why **not** `kea-subscriptions` (almost always)

`subscriptions(({ actions }) => ({ x: (next, prev) => ... }))` installs a redux
subscription. That subscription runs **on every dispatch in the app**, not just when
`x` changes — it checks `x` against the previous value and fires your callback only
when it differs.

That's cheap per-dispatch, but multiplied by the dispatches happening across all
logics, it adds up. There's also a project preference against it: when you reach for
a subscription, almost always you can listen to the action that changed the value
instead, which runs only on that one action.

Two cases where subscriptions are the right tool:

1. **The value is a derived selector you don't own, and there's no action you can
   listen to** — e.g. you need to react to "the active scene's filter object",
   which is composed across multiple logics.
2. **Bidirectional sync between two values that would otherwise loop** — listening
   in both directions creates a cycle; subscriptions break it because they fire
   on value change, not action dispatch.

Both are rare. Default to listeners.

### Workspace constraint

`kea-subscriptions` is only in the `frontend/` workspace `package.json`. **Importing
it from a `products/*` logic fails the build.** Always use listeners there.

## Pattern: same body for multiple actions — `sharedListeners`

If three actions all need to call the same logic, factor it through `sharedListeners`:

```ts
sharedListeners(({ actions, values }) => ({
    reloadIfChanged: () => {
        if (values.shouldReload) actions.loadFoo()
    },
})),
listeners(({ sharedListeners }) => ({
    setFilter: sharedListeners.reloadIfChanged,
    setSort: sharedListeners.reloadIfChanged,
    setDateRange: sharedListeners.reloadIfChanged,
})),
```

Listeners can also be array-valued — the first element can be a shared listener and
the second can be inline:

```ts
listeners(({ sharedListeners }) => ({
    setFilter: [
        sharedListeners.reloadIfChanged,
        ({ filter }) => { /* extra inline behaviour */ },
    ],
})),
```

## Anti-patterns

See [anti-patterns.md](anti-patterns.md) for the consolidated catalogue.

## History

- Commit [`ac783822712`](https://github.com/PostHog/posthog/commit/ac783822712) —
  replaces a `subscriptions` block with `afterMount` + `propsChanged` for a
  prop-derived value in the taxonomic filter. The commit message has the cleanest
  one-line explanation of why the redux-subscription overhead is worth avoiding.
- Commit [`7ef47b68e75`](https://github.com/PostHog/posthog/commit/7ef47b68e75) —
  drops `kea-subscriptions` from a `products/*` logic after the build failed; the
  fix is a listener on the connected action. The canonical example of the
  workspace constraint.
