import { LogicBuilder, beforeUnmount } from 'kea'
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

export function disposables(): LogicBuilder {
    return (logic) => {
        const typedLogic = logic as LogicWithCache

        const safeCleanup = (cleanup: DisposableFunction): void => {
            try {
                cleanup()
            } catch (error) {
                console.error(`[KEA] Disposable cleanup failed in logic ${logic.pathString}:`, error)
            }
        }

        const getManager = (): DisposablesManager => typedLogic.cache.disposables!

        // Initialize disposables manager in cache
        if (!typedLogic.cache.disposables) {
            typedLogic.cache.disposables = {
                registry: new Map(),
                keyCounter: 0,
                add: (setup: SetupFunction, key?: string) => {
                    const manager = getManager()
                    const disposableKey = key ?? `__auto_${manager.keyCounter++}`

                    // If replacing a keyed disposable, clean up the previous one first
                    if (key && manager.registry.has(disposableKey)) {
                        const previousCleanup = manager.registry.get(disposableKey)!
                        safeCleanup(previousCleanup)
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
                    safeCleanup(cleanup)
                    manager.registry.delete(key)
                    return true
                },
            }
        }

        beforeUnmount(() => {
            // Only dispose on final unmount when logic.isMounted() becomes false
            if (!typedLogic.isMounted() && typedLogic.cache.disposables) {
                typedLogic.cache.disposables.registry.forEach((disposable) => {
                    safeCleanup(disposable)
                })
                typedLogic.cache.disposables = null
            }
        })(logic)
    }
}

export const disposablesPlugin: KeaPlugin = {
    name: 'disposables',
}
