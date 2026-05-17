# Anti-patterns — convert on sight

This is the list of shapes that look reasonable but cause specific real problems.
When you see one in code you're reviewing or working in, convert it.

## State containers

### Bare `setInterval` / `setTimeout` with `beforeUnmount` cleanup

```ts
// don't
afterMount(({ actions, cache }) => {
    cache.timer = setInterval(() => actions.poll(), 5000)
}),
beforeUnmount(({ cache }) => clearInterval(cache.timer)),
```

Use `cache.disposables` instead — handles cleanup and auto-pauses on hidden tabs.
See [using-kea-disposables](../../using-kea-disposables/SKILL.md).

### Reducer mirroring a loader's value

```ts
// don't
loaders({ foo: [null, { loadFoo: async () => api.get() }] }),
reducers({ foo: [null, { loadFooSuccess: (_, { foo }) => foo }] }),  // duplicate
```

The loader already gives you `foo`, `fooLoading`, and the success/failure actions.
Delete the reducer.

### `isLoadingFoo` reducer alongside a loader

```ts
// don't
reducers({
  isLoadingFoo: [false, { loadFoo: () => true, loadFooSuccess: () => false }],
})
```

`fooLoading` exists already.

### Reducer that's a deterministic function of other state

```ts
// don't
reducers({
  fullName: [
    '',
    {
      setFirstName: (state, { first }) => `${first} ${state.split(' ')[1] ?? ''}`,
      setLastName: (state, { last }) => `${state.split(' ')[0] ?? ''} ${last}`,
    },
  ],
})
```

Selector. See [state-decision.md](state-decision.md).

### `cache.foo` used to render UI

```ts
// don't
listeners(({ cache, actions }) => ({
  open: () => {
    cache.isOpen = true
  }, // no re-render!
}))
// then in component: cache.isOpen — won't update
```

`cache` has no subscription. Use a reducer.

## Reactions

### `subscriptions` reacting to a value set by an action

```ts
// don't
subscriptions(({ actions }) => ({
  foo: (foo) => {
    if (foo) actions.processFoo()
  },
}))
```

Listen to the action that sets `foo` instead. See
[reacting-to-changes.md](reacting-to-changes.md).

### `subscriptions` in a `products/*` logic

```ts
import { subscriptions } from 'kea-subscriptions' // build fails
```

`kea-subscriptions` is only in `frontend/`. Use listeners.

### `useEffect` in a component reacting to a logic value

```tsx
// don't
const { foo } = useValues(fooLogic)
useEffect(() => {
  if (foo) doSideEffectFoo()
}, [foo])
```

That's a listener. Move it into the logic.

### `propsChanged` body that doesn't guard

```ts
// don't
propsChanged(({ actions, props }) => {
  actions.loadFoo() // fires on every parent re-render
})
```

Guard with `props.fooId !== oldProps.fooId`. React will re-render with referentially
different but structurally equal props.

### A listener that just dispatches one other action

```ts
// don't
listeners(({ actions }) => ({
  setX: ({ x }) => actions.setY(x),
}))
```

Either rename the original action (and let the upstream caller dispatch the right
one), or use `sharedListeners` if multiple actions converge on the same body. A
listener that thinly forwards is a hint that the action shape is wrong.

## Keying

### Keyed logic with no key in the path

```ts
// don't
key((props) => props.fooId),
path(['scenes', 'foo', 'fooLogic']),       // not unique per instance
```

All instances collide in redux. Use `path((key) => ['...', key])`.

### `key` reading from `window`, locals, or another logic

```ts
// don't
key(() => window.currentFooId),
```

Keys must be derivable from props alone. Anything else and two callers with the same
props get different instances — or worse, the same instance when they shouldn't.

### Different key shapes across callers

```ts
// don't
key((props) => props.fooId)
// elsewhere: `${props.fooId}-${props.mode}` for the same logic
```

Pull the key derivation into a helper. Inconsistent keys mean callers don't talk to
the same instance.

## Routing

### Hard-coded URLs

```ts
// don't
urlToAction(({ actions }) => ({ '/foos/:id': ({ id }) => actions.openFoo(id) }))
```

Use `urls.foo(id)` so renames in one place propagate everywhere.

### `actionToUrl` / `urlToAction` feedback loop

The classic: `setQuery` updates URL → URL change fires `setQuery` again → infinite
loop. See [routing.md](routing.md) for guard patterns.

### Plain `urlToAction` on a scene root logic

Scene roots own the URL. Use `tabAwareUrlToAction` so inactive tabs don't hijack
navigation. See [making-scenes-tab-aware](../../making-scenes-tab-aware/SKILL.md).

### Mutating `window.location` directly

```ts
// don't
window.location.href = '/foos/' + id
```

Bypasses kea-router entirely — `urlToAction` won't fire. Use `router.actions.push`.

## Forms

### Validation in the submit handler

```ts
// don't
submit: async (values) => {
  if (!values.email) throw new Error('Email required')
  await api.send(values)
}
```

Validation belongs in `errors`. Submit is for the work.

### Returning `''` from `errors`

```ts
errors: ({ email }) => ({ email: email ? '' : 'Required' }) // '' is truthy!
```

Empty string registers as an error. Use `undefined` for "no error".

### `useState` for form values

```tsx
// don't
const [email, setEmail] = useState('')
const [name, setName] = useState('')
```

That's a `forms` builder waiting to be written.

## Types

### Editing `*LogicType.ts` by hand

It's regenerated by `kea-typegen`. Your changes will be wiped. Change the logic and
re-run typegen.

### Importing the runtime logic when you only need its type

```ts
// don't
import { fooLogic } from './fooLogic'
type FooState = ReturnType<typeof fooLogic.build>['values']
```

```ts
// do
import type { fooLogicType } from './fooLogicType'
type FooState = fooLogicType['values']
```

Importing the runtime forces it to load even if you never call it.

## Mounting and unmounting

### `.mount()` with no stored `unmount`

```ts
// don't
otherLogic.build(props).mount() // leaks
```

Always store the return value and dispose it, ideally via `cache.disposables`.

### Calling `initKea` outside `initKea.ts` / `initKeaTests`

```ts
// don't
import { initKea } from 'initKea'
initKea() // resets the entire store
```

Blows away every mounted logic in the app.

## React integration

### `BindLogic` for a singleton

Singletons have one instance. `BindLogic` is for keyed logics. For singletons, just
call `useValues(fooLogic)`.

### `useValues` + `useActions` in two calls when you can combine

```ts
// OK but verbose if you have many
const { foo } = useValues(fooLogic)
const { setName } = useActions(fooLogic)

// Slightly tighter when bound
const { foo, fooLoading } = useValues(fooLogic)
const { setName, save, reset } = useActions(fooLogic)
```

Not really an anti-pattern, just: don't split into many calls when one of each works.

### Business logic in `useEffect`

If the body of a `useEffect` does anything beyond mounting / focus / DOM, it
probably belongs in a logic listener.

## History

The patterns banned here aren't theoretical — most have a PR behind them where the
thing went wrong in real code:

- [PR #38754](https://github.com/PostHog/posthog/pull/38754) — introduced the
  disposables plugin to replace bare `setInterval` + `beforeUnmount` cleanup.
- [PR #40284](https://github.com/PostHog/posthog/pull/40284) — added auto-pause on
  hidden tab to disposables. This is why polling through `cache.disposables`
  doesn't waste cycles when the user switches away.
- [PR #58691](https://github.com/PostHog/posthog/pull/58691) — fixed a subtle bug
  where disposables registered while the page was hidden would still start
  immediately, defeating the auto-pause.
- PRs [#48039](https://github.com/PostHog/posthog/pull/48039),
  [#48040](https://github.com/PostHog/posthog/pull/48040),
  [#48041](https://github.com/PostHog/posthog/pull/48041), and
  [#48042](https://github.com/PostHog/posthog/pull/48042) — four near-identical
  conversions of "bare `setInterval` poll" to `cache.disposables` across different
  products. Read one of these alongside the disposables skill if you're converting
  similar code.
- Commit [`7ef47b68e75`](https://github.com/PostHog/posthog/commit/7ef47b68e75) —
  why `kea-subscriptions` doesn't work inside a `products/*` logic, and the
  listener-based fix.
