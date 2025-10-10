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
