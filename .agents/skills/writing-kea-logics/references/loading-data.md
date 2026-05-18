# Loading data

Use `kea-loaders` for any state whose value comes from an async source (an HTTP call,
a query helper, anything that returns a promise). Don't roll your own
`isLoadingFoo` reducer.

## Why a loader and not a reducer + listener

A loader on a key `foo` generates:

- A reducer `foo` holding the value
- A boolean selector `fooLoading`
- Actions `loadFoo`, `loadFooSuccess`, `loadFooFailure`
- A global error toast wired up via [`initKea.ts`](../../../../frontend/src/initKea.ts)
- Cancellation via `breakpoint` (next dispatch supersedes the previous in-flight one)

Doing this by hand requires three reducers, a listener with manual try/catch, and
no cancellation. Don't.

## Basic shape

```ts
import { loaders } from 'kea-loaders'

loaders(({ values, props }) => ({
    foo: [
        null as Foo | null,
        {
            loadFoo: async () => {
                return await api.foos.get(props.fooId)
            },
        },
    ],
})),
```

The default value (`null as Foo | null`) is the first element of the tuple. The
handlers object is the second. Each handler is an async function that returns the
next value.

## Handlers can take arguments

```ts
loaders(({ values }) => ({
    results: [
        [] as Result[],
        {
            search: async ({ query }: { query: string }) => {
                return await api.search.list({ query })
            },
        },
    ],
})),
```

Calling `actions.search({ query: 'hi' })` invokes the handler with that payload.
The generated `search` action shape mirrors the argument type.

## Debouncing and cancellation with `breakpoint`

```ts
loaders(({ values }) => ({
    results: [
        [] as Result[],
        {
            search: async ({ query }: { query: string }, breakpoint) => {
                await breakpoint(300)                     // debounce
                const results = await api.search.list({ query })
                breakpoint()                              // discard if superseded
                return results
            },
        },
    ],
})),
```

- `await breakpoint(ms)` throws `BreakPointError` if `search` fires again within `ms`.
- A bare `breakpoint()` after an `await` throws if a newer action has fired. Use this
  after the response comes back to discard stale results.

This is how you build a search-as-you-type without flicker.

## Error handling

The global `loadersPlugin` config in `initKea.ts` shows a toast for every non-2xx
loader failure, **unless** the action key (e.g. `loadFoo`) is in `ERROR_FILTER_ALLOW_LIST`.

If your loader has its own error UI (a banner, an inline message), add the action key
to `ERROR_FILTER_ALLOW_LIST` in `initKea.ts` so users don't see a duplicate toast.

To react to a failure in your own logic, listen for `loadFooFailure`:

```ts
listeners(({ actions }) => ({
    loadFooFailure: ({ error }) => {
        // your custom UI / retry / metrics
    },
})),
```

## Examples in the wild

To find current examples, grep for `loaders(` in `.ts` and `.tsx` files. Patterns to
look for:

- **Single fetch on mount** — a loader called from `afterMount` with no payload.
- **Paginated / appended** — handler reads `values.thing.next` to fetch the next page
  and merges into existing results.
- **Search with debounce** — handler uses `breakpoint(ms)` early to debounce typing.

## Anti-patterns

See [anti-patterns.md](anti-patterns.md) for the consolidated catalogue.
