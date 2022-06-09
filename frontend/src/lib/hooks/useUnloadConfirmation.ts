import { MutableRefObject, useEffect, useRef } from 'react'

interface UnloadConfig {
    unloadMessage: string | null
    onConfirm: (() => void) | undefined
}

export const UNLOAD_REFERENCES: MutableRefObject<UnloadConfig>[] = []

/**
 * This makes sure that unloading the page requires user confirmation - if unloadMessage is set.
 * Uses the browser's native `beforeunload` prevention feature.
 *
 * Additionally, it stores a global list of references used by the `sceneLogic` to determine whether
 * to prevent navigation for history state changes
 *
 * TODO: Integrate this natively to kea-router
 */
export function useUnloadConfirmation(unloadMessage: string | null, onConfirm?: () => void): void {
    const routerUnloadFunctionRef = useRef({
        unloadMessage,
        onConfirm,
    })

    useEffect(() => {
        const unmountFunctions: (() => void)[] = []

        // Native browser unloading
        if (unloadMessage) {
            const beforeUnloadHandler = (e: BeforeUnloadEvent): void => {
                // Cancel the event to show unsaved changes dialog
                e.preventDefault()
                e.returnValue = ''
            }

            window.addEventListener('beforeunload', beforeUnloadHandler)
            unmountFunctions.push(() => window.removeEventListener('beforeunload', beforeUnloadHandler))
        }

        // Kea-router based unloading (used by sceneLogic)
        if (unloadMessage) {
            routerUnloadFunctionRef.current = {
                unloadMessage,
                onConfirm,
            }

            UNLOAD_REFERENCES.push(routerUnloadFunctionRef)

            unmountFunctions.push(() => {
                const index = UNLOAD_REFERENCES.indexOf(routerUnloadFunctionRef)
                if (index > -1) {
                    UNLOAD_REFERENCES.splice(index, 1)
                }
            })
        }

        return () => {
            unmountFunctions.forEach((fn) => fn())
        }
    }, [unloadMessage])
}

// This function is used in `sceneLogic`
export function preventUnload(): boolean {
    const [firstRef] = UNLOAD_REFERENCES
    if (!firstRef || !firstRef.current.unloadMessage) {
        return false
    }

    if (confirm(firstRef.current.unloadMessage)) {
        firstRef.current.onConfirm?.()
        return false
    }

    return true
}
