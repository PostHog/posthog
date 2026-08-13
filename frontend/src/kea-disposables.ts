import type { BuiltLogic, KeaPlugin } from 'kea'

export type DisposableFunction = () => void
export type SetupFunction = () => DisposableFunction

export type DisposableOptions = {
    pauseOnPageHidden?: boolean
}

type DisposableEntry = {
    setup: SetupFunction
    cleanup: DisposableFunction
    options: DisposableOptions
}

export type DisposablesManager = {
    add: (setup: SetupFunction, key?: string, options?: DisposableOptions) => void
    dispose: (key: string) => boolean
    registry: Map<string, DisposableEntry>
    keyCounter: number
    logicPath: string
    /**
     * True once the logic has begun its final unmount. It is set before the registered cleanups
     * run, so a cleanup that wakes a continuation already sees an inert manager. `add` and
     * `dispose` do nothing from that point on, which is what lets async work that outlives the
     * unmount call them unconditionally. Read it when the continuation itself must stop early,
     * for instance before reading `values` on a logic whose reducers are already detached.
     */
    isDisposed: boolean
}

// Type for logic with disposables added
type LogicWithCache = BuiltLogic & {
    cache: { disposables?: DisposablesManager; [key: string]: any }
}

// Global state for visibility tracking
const globalVisibilityState = {
    allManagers: new Set<DisposablesManager>(),
    listenerAttached: false,
    handler: null as (() => void) | null,
}

const safeCleanup = (cleanup: DisposableFunction, logicPath: string): void => {
    try {
        cleanup()
    } catch (error) {
        console.error(`[KEA] Disposable cleanup failed in logic ${logicPath}:`, error)
    }
}

const safeSetup = (setup: SetupFunction, logicPath: string): DisposableFunction | null => {
    try {
        return setup()
    } catch (error) {
        console.error(`[KEA] Disposable setup failed in logic ${logicPath}:`, error)
        return null
    }
}

const pauseAllDisposables = (): void => {
    globalVisibilityState.allManagers.forEach((manager) => {
        manager.registry.forEach((entry) => {
            if (entry.options.pauseOnPageHidden !== false && entry.cleanup) {
                safeCleanup(entry.cleanup, manager.logicPath)
            }
        })
    })
}

const resumeAllDisposables = (): void => {
    globalVisibilityState.allManagers.forEach((manager) => {
        manager.registry.forEach((entry) => {
            if (entry.options.pauseOnPageHidden !== false) {
                const cleanup = safeSetup(entry.setup, manager.logicPath)
                if (cleanup) {
                    entry.cleanup = cleanup
                } else {
                    // Setup failed - replace cleanup with no-op to prevent stale cleanup from running
                    entry.cleanup = () => {}
                }
            }
        })
    })
}

const attachGlobalVisibilityListener = (): void => {
    if (globalVisibilityState.listenerAttached) {
        return
    }

    const handleVisibilityChange = (): void => {
        if (document.hidden) {
            pauseAllDisposables()
        } else {
            resumeAllDisposables()
        }
    }

    globalVisibilityState.handler = handleVisibilityChange
    document.addEventListener('visibilitychange', handleVisibilityChange)
    globalVisibilityState.listenerAttached = true
}

const detachGlobalVisibilityListener = (): void => {
    if (!globalVisibilityState.listenerAttached || !globalVisibilityState.handler) {
        return
    }
    if (globalVisibilityState.allManagers.size === 0) {
        document.removeEventListener('visibilitychange', globalVisibilityState.handler)
        globalVisibilityState.listenerAttached = false
        globalVisibilityState.handler = null
    }
}

const initializeDisposablesManager = (logic: LogicWithCache): void => {
    if (logic.cache.disposables) {
        return
    }

    const manager: DisposablesManager = {
        registry: new Map(),
        keyCounter: 0,
        logicPath: logic.pathString,
        isDisposed: false,
        add: (setup: SetupFunction, key?: string, options?: DisposableOptions) => {
            if (manager.isDisposed) {
                return
            }
            const disposableKey = key ?? `__auto_${manager.keyCounter++}`
            const disposableOptions: DisposableOptions = { pauseOnPageHidden: true, ...options }

            // If replacing a keyed disposable, clean up the previous one first
            if (key && manager.registry.has(disposableKey)) {
                const previousEntry = manager.registry.get(disposableKey)!
                safeCleanup(previousEntry.cleanup, manager.logicPath)
            }

            // If the page is currently hidden and this disposable opts into
            // pause/resume, register it without running setup. resumeAllDisposables
            // will run setup the next time the page becomes visible. Without this,
            // anything calling add() from a listener/loader while hidden (e.g.
            // re-scheduling a poll inside a fetch's `finally`) creates a live
            // timer/listener that should be paused — defeating the auto-pause.
            const startPaused = document.hidden && disposableOptions.pauseOnPageHidden !== false
            if (startPaused) {
                manager.registry.set(disposableKey, {
                    setup,
                    cleanup: () => {},
                    options: disposableOptions,
                })
                return
            }

            // Run setup function to get cleanup function
            const cleanup = safeSetup(setup, manager.logicPath)
            if (cleanup) {
                manager.registry.set(disposableKey, {
                    setup,
                    cleanup,
                    options: disposableOptions,
                })
            }
        },
        dispose: (key: string) => {
            if (manager.isDisposed) {
                return false
            }
            if (!manager.registry.has(key)) {
                return false
            }

            const entry = manager.registry.get(key)!
            safeCleanup(entry.cleanup, manager.logicPath)
            manager.registry.delete(key)
            return true
        },
    }

    logic.cache.disposables = manager

    // Register this manager for global visibility tracking
    globalVisibilityState.allManagers.add(manager)
    attachGlobalVisibilityListener()
}

/**
 * Kea plugin that provides automatic resource cleanup via disposables with smart pause/resume.
 *
 * ## Usage
 *
 * The disposables system is similar to React's useEffect cleanup pattern - you provide
 * a setup function that returns a cleanup function. The cleanup runs automatically when
 * the logic unmounts.
 *
 * ```typescript
 * listeners(({ actions, cache }) => ({
 *     someAction: () => {
 *         // Add a disposable - like useEffect(() => { ... return cleanup }, [])
 *         cache.disposables.add(() => {
 *             // Setup code runs immediately
 *             const intervalId = setInterval(() => {
 *                 actions.pollData()
 *             }, 5000)
 *
 *             // Return cleanup function (like useEffect cleanup)
 *             return () => clearInterval(intervalId)
 *         }, 'pollingInterval') // Optional key for replacing/disposing specific disposables
 *     }
 * }))
 * ```
 *
 * ## Key Features
 *
 * - **Automatic cleanup**: Cleanup functions run when the logic unmounts
 * - **Smart pause/resume**: Disposables automatically pause when page is hidden (NEW!)
 * - **Named disposables**: Use keys to replace or dispose specific resources
 * - **Safe execution**: Errors in cleanup are caught and logged
 * - **Similar to useEffect**: Setup returns cleanup, just like React hooks
 *
 * ## Automatic Pause on Page Hidden
 *
 * By default, all disposables pause when the page is hidden and resume when visible.
 * This dramatically reduces CPU and network usage in background tabs.
 *
 * ```typescript
 * // This automatically pauses when page is hidden
 * cache.disposables.add(() => {
 *     const id = setInterval(() => actions.pollData(), 5000)
 *     return () => clearInterval(id)
 * }, 'polling')
 * ```
 *
 * For critical resources that must remain active (e.g., navigation tracking),
 * opt-out with `pauseOnPageHidden: false`:
 *
 * ```typescript
 * // This keeps running even when page is hidden
 * cache.disposables.add(() => {
 *     window.addEventListener('popstate', handler)
 *     return () => window.removeEventListener('popstate', handler)
 * }, 'navigation', { pauseOnPageHidden: false })
 * ```
 *
 * ## Common Use Cases
 *
 * - Event listeners (window.addEventListener)
 * - Timers (setTimeout, setInterval) - auto-pauses!
 * - Subscriptions (WebSocket, EventSource) - auto-pauses!
 * - External library cleanup
 *
 * @example Replace a disposable
 * ```typescript
 * // Each call with the same key replaces the previous one
 * cache.disposables.add(() => {
 *     const id = setTimeout(() => action(), 1000)
 *     return () => clearTimeout(id)
 * }, 'myTimer')
 *
 * // Later, this replaces the previous timer
 * cache.disposables.add(() => {
 *     const id = setTimeout(() => action(), 2000)
 *     return () => clearTimeout(id)
 * }, 'myTimer')
 * ```
 *
 * @example Manually dispose
 * ```typescript
 * // Stop polling without unmounting
 * cache.disposables.dispose('pollingInterval')
 * ```
 *
 * ## Safe to call after unmount
 *
 * `add` and `dispose` become no-ops once the logic unmounts, so a listener or loader that resumes
 * after the unmount can call them without a null check. When such a continuation must also skip
 * work of its own (dispatching an action, reading `values`), branch on `cache.disposables.isDisposed`.
 */
export const disposablesPlugin: KeaPlugin = {
    name: 'disposables',
    events: {
        afterMount(logic) {
            const typedLogic = logic as LogicWithCache
            initializeDisposablesManager(typedLogic)
        },
        beforeUnmount(logic) {
            const typedLogic = logic as LogicWithCache
            const manager = typedLogic.cache.disposables
            // Only dispose on final unmount when logic.isMounted() becomes false
            if (!typedLogic.isMounted() && manager && !manager.isDisposed) {
                // Unregister from global visibility tracking
                globalVisibilityState.allManagers.delete(manager)

                // Marked before the cleanups run, so that anything a cleanup wakes up (an aborted
                // request resuming inside a `finally`, for instance) sees an inert manager rather
                // than re-registering a resource on a logic that is going away.
                manager.isDisposed = true

                // Clean up all disposables. The manager itself stays on the cache instead of being
                // nulled, because async work that outlives the unmount still reaches for
                // `cache.disposables.dispose(...)`, and a null there throws a TypeError out of the
                // continuation rather than doing nothing.
                manager.registry.forEach((entry) => {
                    safeCleanup(entry.cleanup, typedLogic.pathString)
                })
                manager.registry.clear()

                // Detach global listener if no more managers
                detachGlobalVisibilityListener()
            }
        },
    },
}
