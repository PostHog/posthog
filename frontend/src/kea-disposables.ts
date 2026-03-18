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

type DisposablesManager = {
    add: (setup: SetupFunction, key?: string, options?: DisposableOptions) => void
    dispose: (key: string) => boolean
    registry: Map<string, DisposableEntry>
    keyCounter: number
    logicPath: string
}

// Type for logic with disposables added
type LogicWithCache = BuiltLogic & {
    cache: { disposables?: DisposablesManager | null; [key: string]: any }
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

    const getManager = (): DisposablesManager => logic.cache.disposables!

    const manager: DisposablesManager = {
        registry: new Map(),
        keyCounter: 0,
        logicPath: logic.pathString,
        add: (setup: SetupFunction, key?: string, options?: DisposableOptions) => {
            const manager = getManager()
            const disposableKey = key ?? `__auto_${manager.keyCounter++}`
            const disposableOptions: DisposableOptions = { pauseOnPageHidden: true, ...options }

            // If replacing a keyed disposable, clean up the previous one first
            if (key && manager.registry.has(disposableKey)) {
                const previousEntry = manager.registry.get(disposableKey)!
                safeCleanup(previousEntry.cleanup, manager.logicPath)
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
            const manager = getManager()
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
            // Only dispose on final unmount when logic.isMounted() becomes false
            if (!typedLogic.isMounted() && typedLogic.cache.disposables) {
                // Unregister from global visibility tracking
                globalVisibilityState.allManagers.delete(typedLogic.cache.disposables)

                // Clean up all disposables
                typedLogic.cache.disposables.registry.forEach((entry) => {
                    safeCleanup(entry.cleanup, typedLogic.pathString)
                })
                typedLogic.cache.disposables = null

                // Detach global listener if no more managers
                detachGlobalVisibilityListener()
            }
        },
    },
}
