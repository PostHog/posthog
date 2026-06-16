/**
 * Tiny pub-sub store backing the Storybook router mocks.
 *
 * The `next/navigation` + `next/link` mocks are vite-aliased modules
 * — they live outside the story's React tree, so they can't read
 * story-local state directly. Instead, they read from this store via
 * `useSyncExternalStore`, and `<Link>` / `router.push` write to it
 * via `navigate()`. The story renders a `<StoryRoutes>` switch that
 * subscribes to the same store and picks which page to mount.
 *
 * `params` is set by the route-switch *after* it matches the path,
 * so calls to `useParams()` inside page components return the right
 * dynamic-segment values (e.g. `{ slug: 'weekly-digest' }`).
 */

interface RouterState {
    /** Full href including search portion, e.g. `/agents/foo/sessions?id=abc` */
    path: string
    /** Dynamic segments parsed by the route switch. */
    params: Record<string, string>
}

let state: RouterState = { path: '/agents', params: {} }
const listeners = new Set<() => void>()

function notify(): void {
    for (const l of listeners) {
        l()
    }
}

export function subscribe(listener: () => void): () => void {
    listeners.add(listener)
    return () => listeners.delete(listener)
}

export function getSnapshot(): RouterState {
    return state
}

/** Replace the current path. Used by `router.push/replace` and `<Link>` clicks. */
export function navigate(href: string): void {
    if (href === state.path) {
        return
    }
    state = { path: href, params: state.params }
    notify()
}

/** Set the dynamic-segment params after a route match. Called by the route switch. */
export function setParams(params: Record<string, string>): void {
    // Object.keys cheap equality — params are tiny so this is fine.
    const keys = Object.keys(params)
    const stateKeys = Object.keys(state.params)
    if (keys.length === stateKeys.length && keys.every((k) => state.params[k] === params[k])) {
        return
    }
    state = { path: state.path, params }
    notify()
}

/** Reset the store. Used by `<StoryRoutes initialPath="...">` on mount. */
export function reset(path: string): void {
    state = { path, params: {} }
    notify()
}
