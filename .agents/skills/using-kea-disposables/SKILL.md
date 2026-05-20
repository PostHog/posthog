---
name: using-kea-disposables
description: 'Use when adding timers (`setInterval`, `setTimeout`), event listeners (`window.addEventListener`, `document.addEventListener`, `MediaQueryList.addEventListener`), or any other resource that needs cleanup inside a kea logic. Every logic has `cache.disposables.add(setup, key?, options?)` and `cache.disposables.dispose(key)` available via the globally registered `disposablesPlugin` (`frontend/src/kea-disposables.ts`). Replaces the bare `cache.foo = setInterval(...)` + `beforeUnmount: clearInterval(cache.foo)` pattern and auto-pauses background work when the tab is hidden.'
---

# Using kea disposables

Every kea logic in this repo has `cache.disposables` injected by the local `disposablesPlugin` (`frontend/src/kea-disposables.ts`, registered globally in `frontend/src/initKea.ts`). Reach for it whenever you create a resource that needs explicit teardown — the plugin runs cleanup on unmount and automatically pauses background work when the tab is hidden.

**Do not add a `beforeUnmount` for cleanup.** The plugin runs the cleanup function you return from `setup` automatically when the logic unmounts (and re-runs setup/cleanup around tab visibility changes). If you find yourself writing a `beforeUnmount` whose only job is to `clearInterval` / `clearTimeout` / `removeEventListener` something registered earlier in the same logic, register that resource through `cache.disposables.add(...)` instead and delete the `beforeUnmount`. Reserve `beforeUnmount` for teardown that _isn't_ a resource you control (e.g. flushing state, persisting to localStorage, calling a third-party `dispose()`).

## Use this skill when

- Adding `setInterval` or `setTimeout` inside `afterMount`, a listener, or a subscription
- Adding `window.addEventListener`, `document.addEventListener`, or `MediaQueryList.addEventListener`
- Adding any subscription that needs explicit teardown (WebSocket, EventSource, ResizeObserver, IntersectionObserver, etc.)
- Reviewing or editing a logic with a bare `cache.<thing>` plus a matching `beforeUnmount` cleanup — convert it
- A state change should tear down a previously-registered timer or listener early

## The pattern

```ts
cache.disposables.add(
    setup,    // () => () => void — runs immediately; MUST return a cleanup function
    key?,     // string — re-adding with the same key disposes the previous one first
    options?, // { pauseOnPageHidden?: boolean } — default true: cleanup runs on hide, setup re-runs on show
)
```

Canonical example (`frontend/src/layout/navigation/noEventsBannerLogic.ts:14-21`):

```ts
afterMount(({ actions, cache }) => {
    cache.disposables.add(() => {
        const pollTimer = window.setInterval(() => {
            actions.loadCurrentTeam()
        }, POLL_INTERVAL_MS)
        return () => clearInterval(pollTimer)
    })
}),
```

## Choosing a key

- **No key** — fire-and-forget; cleaned up only on unmount. Fine for one-shot listeners registered in `afterMount`.
- **Named key** — needed when:
  - You'll call `cache.disposables.dispose(key)` later to stop it early
  - The same setup may be re-added and each call should replace the previous one (spam-replacement)

## `pauseOnPageHidden`

The default (`true`) is correct for almost everything — polling, animation tickers, hover timers. Background tabs stop doing work and resume on focus, which dramatically reduces CPU and network cost.

Opt out (`{ pauseOnPageHidden: false }`) only when the listener must keep firing while the page is hidden:

- Listeners for events that can genuinely fire while the tab is hidden — e.g. `storage` (writes from another tab), `online` / `offline`, `message` (from web workers, service workers, or other windows)
- A `visibilitychange` listener itself — the whole point is to observe hide/show
- Anything the user expects to keep running while the tab is hidden

Note: `popstate` cannot fire on a hidden tab (it's user-driven), so pausing on hide is fine — see the toolbar example below.

## Calling `dispose()` to stop early

`cache.disposables.dispose('key')` tears down one specific resource without unmounting the logic. Use it when a state transition should end the resource — pause/resume a poller, stop a hover-only ticker on mouseleave, close a modal-scoped listener.

## Examples in the codebase

**Unnamed `setInterval` poller** — see the canonical example in [The pattern](#the-pattern) (`frontend/src/layout/navigation/noEventsBannerLogic.ts:14-21`).

**Keyed intervals with `dispose()` on hover-end / pause** — `frontend/src/lib/components/LiveUserCount/liveUserCountLogic.ts:94-118`

```ts
setIsHovering: ({ isHovering }) => {
    if (isHovering) {
        actions.setNow(new Date())
        cache.disposables.add(() => {
            const intervalId = setInterval(() => actions.setNow(new Date()), 500)
            return () => clearInterval(intervalId)
        }, 'nowInterval')
    } else {
        cache.disposables.dispose('nowInterval')
    }
},
pauseStream: () => {
    cache.disposables.dispose('statsInterval')
},
resumeStream: () => {
    actions.pollStats()
    cache.disposables.add(() => {
        const intervalId = setInterval(() => actions.pollStats(), props.pollIntervalMs ?? 30000)
        return () => clearInterval(intervalId)
    }, 'statsInterval')
},
```

**`setTimeout` with key for spam-replacement** — `frontend/src/scenes/session-recordings/player/sessionRecordingPlayerLogic.ts:1837-1846`

```ts
showSeekIndicator: () => {
    // Same key auto-disposes the previous timer when spamming
    cache.disposables.add(() => {
        const timerId = setTimeout(() => actions.hideSeekIndicator(), 600)
        return () => clearTimeout(timerId)
    }, 'seekIndicatorTimer')
},
```

**Multiple keyed window listeners in one `afterMount`** — `frontend/src/toolbar/bar/toolbarLogic.ts:655-688`

```ts
cache.disposables.add(() => {
  const clickListener = (e: MouseEvent): void => {
    /* ... */
  }
  window.addEventListener('mousedown', clickListener)
  return () => window.removeEventListener('mousedown', clickListener)
}, 'clickListener')

// popstate only fires on user-initiated back/forward, so a hidden tab won't
// generate events — pausing on hide (the default) is fine here. Opt out
// only if you must observe popstates while the tab is in the background.
cache.disposables.add(() => {
  const popstateHandler = (): void => actions.maybeSendNavigationMessage()
  window.addEventListener('popstate', popstateHandler)
  return () => window.removeEventListener('popstate', popstateHandler)
}, 'popstateListener')
```

**`visibilitychange` listener with `pauseOnPageHidden: false`** — `frontend/src/scenes/product-tours/productTourLogic.ts:647-663`

```ts
openToolbarModal: () => {
    cache.disposables.add(
        () => {
            const handler = (): void => {
                if (document.visibilityState === 'hidden') {
                    actions.handleToolbarTabVisibility()
                }
            }
            document.addEventListener('visibilitychange', handler)
            return () => document.removeEventListener('visibilitychange', handler)
        },
        'toolbarModalVisibility',
        { pauseOnPageHidden: false }
    )
},
closeToolbarModal: () => {
    cache.disposables.dispose('toolbarModalVisibility')
},
```

**`MediaQueryList` listener in `events(afterMount)`** — `frontend/src/layout/navigation-3000/themeLogic.ts:108-118`

```ts
events(({ cache, actions }) => ({
    afterMount() {
        cache.disposables.add(() => {
            const prefersColorSchemeMedia = window.matchMedia('(prefers-color-scheme: dark)')
            const onPrefersColorSchemeChange = (e: MediaQueryListEvent): void =>
                actions.syncDarkModePreference(e.matches)
            prefersColorSchemeMedia.addEventListener('change', onPrefersColorSchemeChange)
            return () => prefersColorSchemeMedia.removeEventListener('change', onPrefersColorSchemeChange)
        }, 'prefersColorSchemeListener')
    },
})),
```

## Anti-patterns to convert

Bare `cache.<thing>` + `beforeUnmount` cleanup is the pattern this plugin replaces. Convert these on sight.

**Before** (`frontend/src/lib/components/HedgehogMode/hedgehogModeLogic.ts:205-215`):

```ts
afterMount(({ actions, cache }) => {
    cache.syncInterval = setInterval(() => actions.syncFromState(), 1000)
}),
beforeUnmount(({ cache }) => {
    if (cache.syncInterval) {
        clearInterval(cache.syncInterval)
        cache.syncInterval = null
    }
}),
```

**After** — note the `beforeUnmount` block is gone entirely; the cleanup function returned from `setup` is what the plugin runs on unmount:

```ts
afterMount(({ actions, cache }) => {
    cache.disposables.add(() => {
        const id = setInterval(() => actions.syncFromState(), 1000)
        return () => clearInterval(id)
    }, 'syncInterval')
}),
```

Other open conversion targets:

- `frontend/src/scenes/welcome/welcomeDialogLogic.ts:325-345` — bare `window.addEventListener('storage', ...)` with `cache.storageHandler` stashed manually
- `frontend/src/scenes/inbox/inboxSceneLogic.ts:260-267` — bare `setInterval` cleared by hand on every state change
