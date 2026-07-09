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

### `try`/`catch` around the whole loader handler

```ts
// don't
loadFoo: async () => {
    try {
        return await api.foos.get(props.fooId)
    } catch (e) {
        return null
    }
},
```

`kea-loaders` already catches and emits `loadFooFailure` with the error. Listen for
that action if you need custom handling, and only re-throw inside the handler if you
genuinely need to abort the loader machinery.

### Non-async logic in a loader

If the handler doesn't `await` anything, it's a reducer or selector wearing a loader's
hat. Loaders are for async — the action/success/failure trio and the `xLoading` boolean
are noise when the work is synchronous.

## Loading data and persistence

### `localStorage.setItem` directly inside a listener

Two tabs will race; serialisation is your problem; you've reinvented `{ persist: true }`.
Use the kea-localstorage plugin — second slot of a reducer tuple.

### Persisted loader results

```ts
// don't
foo: [
    null as Foo | null,
    { persist: true },                       // serves stale data on next mount
    { loadFooSuccess: (_, { foo }) => foo },
],
```

Loaders re-fetch on mount anyway, so persisting the value just shows stale data
during the gap. Persist only if the previous value is genuinely better than a loading
spinner.

### Persisting a selector

Selectors aren't reducers. Persist the inputs and recompute.

### `window.matchMedia(...)` registered without going through `cache.disposables`

Same shape as bare `setInterval` — you'll leak a listener on unmount. Wrap the
`addEventListener` / `removeEventListener` pair in `cache.disposables.add(...)`. See
[using-kea-disposables](../../using-kea-disposables/SKILL.md).

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
// smells off
listeners(({ actions }) => ({
  setX: ({ x }) => actions.setY(x),
}))
```

Sometimes this is the right shape — adapting payload shape across a logic boundary, or
re-firing a connected action you don't own. But if you do own both actions and they
take the same args, this is a hint that the action shape is wrong. Check whether you
can rename the upstream action, or whether two callers should share a body via
`sharedListeners`.

### Polling without a stop condition

If the thing you're waiting on can finish (a job, a migration, a build), listen for
the terminal state and `cache.disposables.dispose('pollKey')`. Otherwise the poller
hammers the API indefinitely while the page is open.

### Polling on a singleton when only a subset of views need fresh data

Mount the polling logic from the view that needs it (via `useMountedLogic` or
`useValues`) so the timer is scoped to where it matters.

### `setInterval(... 0)` as "next tick"

If you need to act on the next event-loop turn, use a listener on the action that
should trigger the work, or `requestAnimationFrame` for frame-boundary cases.
`setInterval(0)` is a wasted timer.

## Keying

### Keyed logic with no key in the path

```ts
// don't
key((props) => props.fooId),
path(['scenes', 'foo', 'fooLogic']),       // key not visible in path
```

Instance identity is handled by `key`, but PostHog convention is to also append the
key to `path` so the key shows up in redux devtools, in typegen output, and in any
log lines that include the logic path. Use `path((key) => ['...', key])`.

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

### Mounting a keyed logic with `fooLogic()` (no props)

Same as `fooLogic({})` — keys to `undefined`. All such callers share one phantom
instance. Always pass props at the call site.

### Forgetting to type the export when the logic is keyed

```ts
// don't (call-site types end up as any)
export const fooLogic = kea<fooLogicType>([
  props({} as FooLogicProps),
  key((props) => props.fooId),
  // ...
])
```

```ts
// do
export const fooLogic: LogicWrapper<fooLogicType> = kea<fooLogicType>([...])
```

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

### Mutating `window.location` directly

```ts
// don't
window.location.href = '/foos/' + id
```

Bypasses kea-router entirely — `urlToAction` won't fire. Use `router.actions.push`.

### `useNavigate` / `useParams` in a component when there's a logic

URL is logic state. Move the reaction to `urlToAction` and the navigation to
`actionToUrl` (or `router.actions.push` inside a listener) so the logic owns the
behaviour and the component shrinks back to view code.

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
errors: ({ email }) => ({ email: email ? '' : 'Required' }) // '' is not undefined — counts as a present error
```

`kea-forms` treats any non-`undefined` value in the errors map as a present error,
so `''` and `'Required'` both make the field invalid. Return `undefined` for
"no error".

### Side effects inside `errors`

`errors` re-runs on every keystroke. Keep it pure — no logging, no analytics, no
async work. Reach for a listener on `setFooValues` if you need to react to typing.

### `useState` for form values

```tsx
// don't
const [email, setEmail] = useState('')
const [name, setName] = useState('')
```

That's a `forms` builder waiting to be written.

### Manual `setFoo` / `setFooValue` chains instead of `<Field>`

```tsx
// don't
<LemonInput value={values.signup.email} onChange={(v) => actions.setSignupValue('email', v)} />
```

`<Field name="email">` already wires the change handler. Use it; the component shrinks.

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

### Reading another logic's state from a render function

```tsx
// don't
function FooView(): JSX.Element {
  const x = otherLogic.values.x // no subscription — won't re-render when x changes
  return <div>{x}</div>
}
```

Use `useValues(otherLogic)` so the component subscribes and re-renders on change.

### `useEffect` to mount another logic and dispatch an action

```tsx
// don't
useEffect(() => {
  otherLogic(props).actions.x()
}, [])
```

Use `useMountedLogic(otherLogic)` to manage the lifecycle, plus `useActions` to call
the action — or do the mounting inside a logic that owns the relationship.

### `connect.values: [otherLogic, ['everything']]` copy-paste

Pull only the names you actually use. The generated types are tighter, downstream
refactors stay obvious, and unused names won't trigger spurious re-renders.

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
- [PR #48042](https://github.com/PostHog/posthog/pull/48042) — canonical example of
  converting a "bare `setInterval` poll" to `cache.disposables` (the managed-migrations
  logic). Read this alongside the disposables skill if you're doing the same
  conversion in another product.
- Commit [`7ef47b68e75`](https://github.com/PostHog/posthog/commit/7ef47b68e75) —
  why `kea-subscriptions` doesn't work inside a `products/*` logic, and the
  listener-based fix.
