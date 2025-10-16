import type { BuiltLogic, KeaPlugin } from 'kea'

export type DisposableFunction = () => void
export type SetupFunction = () => DisposableFunction

type DisposablesManager = {
    add: (setup: SetupFunction, key?: string) => void
    dispose: (key: string) => boolean
    registry: Map<string, DisposableFunction>
    keyCounter: number
}

// Type for logic with disposables added
type LogicWithCache = BuiltLogic & {
    cache: { disposables?: DisposablesManager | null; [key: string]: any }
}

const safeCleanup = (cleanup: DisposableFunction, logicPath: string): void => {
    try {
        cleanup()
    } catch (error) {
        console.error(`[KEA] Disposable cleanup failed in logic ${logicPath}:`, error)
    }
}

const initializeDisposablesManager = (logic: LogicWithCache): void => {
    if (logic.cache.disposables) {
        return
    }

    const getManager = (): DisposablesManager => logic.cache.disposables!

    logic.cache.disposables = {
        registry: new Map(),
        keyCounter: 0,
        add: (setup: SetupFunction, key?: string) => {
            const manager = getManager()
            const disposableKey = key ?? `__auto_${manager.keyCounter++}`

            // If replacing a keyed disposable, clean up the previous one first
            if (key && manager.registry.has(disposableKey)) {
                const previousCleanup = manager.registry.get(disposableKey)!
                safeCleanup(previousCleanup, logic.pathString)
            }

            // Run setup function to get cleanup function
            const cleanup = setup()
            manager.registry.set(disposableKey, cleanup)
        },
        dispose: (key: string) => {
            const manager = getManager()
            if (!manager.registry.has(key)) {
                return false
            }

            const cleanup = manager.registry.get(key)!
            safeCleanup(cleanup, logic.pathString)
            manager.registry.delete(key)
            return true
        },
    }
}

/**
 * Kea plugin that provides automatic resource cleanup via disposables.
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
 * - **Named disposables**: Use keys to replace or dispose specific resources
 * - **Safe execution**: Errors in cleanup are caught and logged
 * - **Similar to useEffect**: Setup returns cleanup, just like React hooks
 *
 * ## Common Use Cases
 *
 * - Event listeners (window.addEventListener)
 * - Timers (setTimeout, setInterval)
 * - Subscriptions (WebSocket, EventSource)
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
                typedLogic.cache.disposables.registry.forEach((disposable) => {
                    safeCleanup(disposable, typedLogic.pathString)
                })
                typedLogic.cache.disposables = null
            }
        },
    },
}
