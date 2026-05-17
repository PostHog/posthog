# Persisting state

Two plugins cover persistence concerns:

- `kea-localstorage` — survive reload by writing a reducer to `localStorage`
- `kea-window-values` — derive values from `window` (`innerWidth`, `fullscreenElement`)
  and stay in sync as the window changes

Both are globally registered in `initKea.ts`, so any logic can use them.

## `{ persist: true }` — survive reload

Make a reducer's value survive page reload by passing `{ persist: true }` as the
second element of the reducer tuple:

```ts
reducers({
  themeMode: [
    'system' as ThemeMode, // default
    { persist: true }, // persistence config
    { setThemeMode: (_, { themeMode }) => themeMode }, // handlers
  ],
})
```

The plugin writes the value to `localStorage` keyed by the logic's path. On mount it
hydrates the reducer from storage if a value exists, otherwise uses the default.

### When persist is the right answer

- User preferences (theme, sidebar width, default tab)
- Dismissed-once UI (tooltip dismissals, onboarding banners)
- Filter state that should survive reload but isn't worth a URL

### When persist is the wrong answer

- **Server state.** Use a loader. localStorage will go stale immediately and confuse
  the next session.
- **Auth / identity.** That belongs in the API layer (cookies / auth headers).
- **Anything sensitive.** localStorage is plaintext, JS-readable, and synced by some
  browser profiles.
- **State another tab also writes.** localStorage is shared; concurrent writes race.

### Resetting

If you change a reducer's shape, the old value in localStorage will type-mismatch.
Either:

- Add migration logic in the reducer default (read the old shape, transform).
- Change the path (rare — breaks everything else).

Don't silently break — at minimum, the reducer default should be a valid value if
the stored shape doesn't match.

## `windowValues` — read live values from `window`

```ts
import { windowValues } from 'kea-window-values'

windowValues(() => ({
    fullscreen: (window: Window) => !!window.document.fullscreenElement,
    mobileLayout: (window: Window) => window.innerWidth < 992,
})),
```

Each key becomes a selector. The plugin re-evaluates them on `resize` / `scroll` /
`fullscreenchange` and triggers a re-render for subscribers.

### When this is the right answer

- Responsive breakpoints in a logic (so the JSX stays clean)
- Reading `document.fullscreenElement` for fullscreen-aware UI

### When this is the wrong answer

- **Media queries.** `MediaQueryList.addEventListener('change', ...)` via
  `cache.disposables` is more efficient and gives you the exact breakpoint.
- **`window.innerWidth` checks inside a render function.** Use a `windowValues` entry
  so it's reactive.

## Anti-patterns

See [anti-patterns.md](anti-patterns.md) for the consolidated catalogue.
