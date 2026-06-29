# Routing — syncing state with the URL

PostHog uses `kea-router` for URL state. Two builders cover almost everything:

- `urlToAction` — URL change → fire an action
- `actionToUrl` — action fires → update the URL

For imperative navigation, dispatch `router.actions.push(urls.foo())` inside a listener.

## Why a router builder and not `useNavigate` / `useParams`

- The logic owns URL state, not the component. Reload-safe, deep-linkable, and the
  state survives React unmounts.
- One place to update both internal state and the URL together — no two-step "set
  state, then call navigate" dance.
- Works inside a logic that isn't bound to any component (e.g. a singleton).

## `urlToAction` — react to URL changes

```ts
urlToAction(({ actions }) => ({
    [urls.fooList()]: () => {
        actions.setSelectedId(null)
    },
    [`${urls.foo()}/:id`]: ({ id }) => {
        actions.setSelectedId(id ?? null)
    },
})),
```

- Keys are URL patterns; `:id`-style placeholders are extracted into the first arg.
- All matching patterns fire, in order. Put the most-specific first if you care.
- Use `urls.foo()` helpers (in `frontend/src/scenes/urls.ts`) — don't hard-code paths.

## `actionToUrl` — update the URL from an action

```ts
actionToUrl(({ values }) => ({
    setSelectedId: ({ id }) => (id ? urls.foo(id) : urls.fooList()),
    setFilter: ({ filter }) => [
        router.values.location.pathname,
        { q: filter },                       // searchParams (object — router serialises it)
        router.values.hashParams,            // hashParams (object — keep existing hash)
        { replace: true },                   // don't push history entry
    ],
})),
```

Return shapes:

- A string — replaces the pathname.
- `[pathname, searchParams, hashParams, options]` — full control. `searchParams` and
  `hashParams` are **objects**; the router serialises them. Don't pass a raw query
  string here — it'll get URL-encoded twice.
- Nothing / `undefined` — no URL change for this action.

Use `{ replace: true }` for filter/sort changes so the back button skips through
intermediate states.

## Avoiding the feedback loop

The classic bug: `setX` updates the URL, the URL change fires `setX` again with the
same value, loop.

Two ways out:

```ts
// 1. Check the value didn't change
urlToAction(({ actions, values }) => ({
    [urls.foo()]: (_, search) => {
        if (search.q !== values.query) {
            actions.setQuery(search.q ?? '')
        }
    },
})),

// 2. Only react to user-initiated navigations
urlToAction(({ actions }) => ({
    [urls.foo()]: (_, search, hash, { method }) => {
        if (method === 'REPLACE') return        // ignore our own replace
        actions.setQuery(search.q ?? '')
    },
})),
```

`method` is one of `PUSH | REPLACE | POP`. `POP` is back/forward, `PUSH`/`REPLACE`
are from `actionToUrl` or imperative navigation.

## Imperative navigation

Inside a listener:

```ts
import { router } from 'kea-router'

listeners(() => ({
    createFooSuccess: ({ foo }) => {
        router.actions.push(urls.foo(foo.id))
    },
})),
```

`router.actions.push(url)` for a normal navigation, `.replace(url)` to avoid pushing
history. Prefer `actionToUrl` over imperative navigation when the action and URL are
the same concept — let the builder do the wiring.

## Anti-patterns

See [anti-patterns.md](anti-patterns.md) for the consolidated catalogue.
