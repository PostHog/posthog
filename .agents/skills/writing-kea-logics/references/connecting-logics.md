# Connecting logics and React

Two parts to this: kea-to-kea (`connect`, imperative mounting) and kea-to-React
(`useValues`, `useActions`, `BindLogic`).

## Pulling values and actions from another logic — `connect`

```ts
connect(() => ({
  values: [teamLogic, ['currentTeamId', 'currentTeam'], userLogic, ['user']],
  actions: [teamLogic, ['loadCurrentTeam']],
  logic: [eventUsageLogic], // mount-only, no values pulled
}))
```

- **Always use the function form `connect(() => ({...}))`.** Defers evaluation past
  module load, so circular imports don't blow up.
- `values: [logic, ['a', 'b'], otherLogic, ['c']]` flattens — each logic followed by
  its names. The names become available on `values` inside the logic.
- `actions: [logic, ['x']]` lets you both dispatch `actions.x()` and listen for `x`
  in your own `listeners`.
- `logic: [otherLogic]` mounts the logic without pulling anything. Use when you need
  the other logic running for its side effects (e.g. analytics, polling).

### Connecting to a keyed logic

```ts
connect((props: FooLogicProps) => ({
  values: [barLogic(props), ['something']],
}))
```

Take props and pass them through to the keyed logic. Same props → same key → same
instance, so you talk to the same one as everyone else with the same props.

## Mounting another logic from inside a logic

When you need a logic's _instance_ (to track it, find it, or hand it to something),
use `.build()` + `.mount()`:

```ts
listeners(({ actions, cache }) => ({
  openInsight: ({ insightId }) => {
    const logic = insightLogic.build({ dashboardItemId: insightId })
    const unmount = logic.mount()
    cache.disposables.add(() => unmount, `insightRef:${insightId}`)
  },
}))
```

- `.build(props)` returns the wrapper without mounting.
- `.mount()` mounts it and returns an unmount function.
- Register the unmount with `cache.disposables` so it's cleaned up automatically.

### `findMounted` — peek without mounting

```ts
const logic = otherLogic.findMounted({ id })
if (logic) {
  actions.doSomething(logic.values.x)
}
```

Returns `undefined` if the logic isn't mounted. Use when "if it happens to be
running, sync with it; otherwise nothing".

## Wiring up React — `useValues` / `useActions`

```tsx
import { useActions, useValues } from 'kea'

function FooView({ fooId }: { fooId: string }): JSX.Element {
  const logic = fooLogic({ fooId }) // for keyed logics
  const { foo, fooLoading } = useValues(logic)
  const { setName } = useActions(logic)
  return <input value={foo?.name ?? ''} onChange={(e) => setName(e.target.value)} />
}
```

For singletons, drop the `(props)`: `useValues(fooLogic)`.

These hooks are how a component subscribes to a logic. `useValues` re-renders the
component when the chosen values change; `useActions` returns stable action refs.

## `BindLogic` — provide a keyed instance to a subtree

If a parent component knows the key and its children don't want to thread props
everywhere, wrap them in `BindLogic`:

```tsx
<BindLogic logic={fooLogic} props={{ fooId }}>
  <FooHeader /> {/* useValues(fooLogic) resolves to the bound instance */}
  <FooDetails />
  <FooFooter />
</BindLogic>
```

Inside the subtree, `useValues(fooLogic)` (no props) works because `BindLogic` set
the context.

Nest `BindLogic` when you have multiple keyed dependencies:

```tsx
<BindLogic logic={dataNodeLogic} props={dataNodeProps}>
  <BindLogic logic={dataVisualizationLogic} props={vizProps}>
    <SQLEditor />
  </BindLogic>
</BindLogic>
```

## `useMountedLogic` — own the logic lifecycle

```tsx
function FooHost(): JSX.Element {
  useMountedLogic(fooLogic) // mounts on mount, unmounts on unmount
  return <FooView />
}
```

Use when a logic should live exactly as long as a particular component, and no one
else is going to mount it. `useValues` and `useActions` already mount as a side
effect, so `useMountedLogic` is only needed when no values are pulled.

## `useAttachedLogic` — keep a logic mounted through the scene

For scene-level child logics that must survive React unmounts, use `useAttachedLogic`.

## Anti-patterns

See [anti-patterns.md](anti-patterns.md) for the consolidated catalogue.
