# Keyed logics — many instances of one logic

Most logics are singletons — one global instance, accessed everywhere. But when you
need one instance per resource (per insight, per dashboard, per chat thread), you
key the logic by the resource id.

## Why a keyed logic and not a singleton

A singleton holding `currentFooId` and `currentFoo` works for one foo at a time.
Open two foos side-by-side (split view, tab system) and they fight over the same
state.

A keyed logic creates an independent instance per key — same code, separate state,
separate listeners, separate cache. The redux store puts each instance under its own
path.

## The minimum keyed shape

```ts
import { actions, kea, key, path, props, reducers } from 'kea'

import type { fooLogicType } from './fooLogicType'

export interface FooLogicProps {
  fooId: string
}

export const fooLogic = kea<fooLogicType>([
  props({} as FooLogicProps), // 1
  key((props) => props.fooId), // 2
  path((key) => ['scenes', 'foo', 'fooLogic', key]), // 3
  actions({
    /* ... */
  }),
  reducers({
    /* ... */
  }),
])
```

1. **`props({} as FooLogicProps)`** declares the typed default. Always cast — kea
   can't otherwise type-check the props at the `key` function.
2. **`key`** picks one field (or a composite) out of props as the instance
   identifier. Same key → same instance.
3. **`path` includes the key.** Without this, every instance writes to the same
   redux node and they collide. The function form `path((key) => [...])` is what
   wires the key in.

## Calling a keyed logic

```ts
// In another logic
connect((props) => ({ values: [fooLogic(props), ['foo']] }))

// In a component
const logic = fooLogic({ fooId })
const { foo } = useValues(logic)
const { setName } = useActions(logic)
```

`fooLogic(props)` returns the wrapper for that specific instance — same return type
as `fooLogic.build(props)` but lazily mounted on use.

## Composite keys

When a single id isn't enough, build a composite key with a helper that lives next
to the logic:

```ts
// keyForInsightLogicProps.ts
export function keyForInsightLogicProps(defaultKey: string) {
  return (props: InsightLogicProps): string => {
    return props.dashboardItemId ? `${props.dashboardItemId}::${props.dashboard ?? 'no-dashboard'}` : defaultKey
  }
}

// fooLogic.ts
key((props) => keyForInsightLogicProps('new')(props))
```

The helper makes the key predictable and reusable across `connect` calls — anyone
who needs to talk to the same instance can compute the same key.

## Required vs optional keys

```ts
// Throws if fooId is missing — for logics that must have a resource
key((props) => {
    if (!props.fooId) throw new Error('Must init fooLogic with fooId')
    return props.fooId
}),

// Falls back for "new" / "draft" cases
key((props) => props.fooId ?? 'new'),
```

Throwing is friendlier than silently mounting under a key like `undefined`, which
will mysteriously share state across all the places that forgot the prop.

## Reacting to a key or prop change

Two distinct cases — distinguish them:

- **Props change, key stays the same.** Same logic instance, new props. Use
  `propsChanged` to react.
- **Key changes.** A different instance is mounted; the old one is torn down when its
  React subscriber unmounts. `propsChanged` does **not** fire across instances —
  it's a same-instance hook. The new instance gets `afterMount` as usual.

```ts
// Same instance, new props (a non-keyed prop changes):
propsChanged(({ actions, props }, oldProps) => {
    if (props.filter !== oldProps.filter) {
        actions.loadFoo()
    }
}),

// New instance via key change: afterMount fires on the new one as usual
afterMount(({ actions }) => {
    actions.loadFoo()
}),
```

## Typing the export

```ts
export const fooLogic: LogicWrapper<fooLogicType> = kea<fooLogicType>([...])
```

The explicit `LogicWrapper<fooLogicType>` annotation gives you the right overloads
for calling `fooLogic(props)`. For singletons it's not needed; for keyed logics it
makes the call-site types behave.

## Anti-patterns

See [anti-patterns.md](anti-patterns.md) for the consolidated catalogue.
