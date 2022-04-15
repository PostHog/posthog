import { useEffect } from 'react'

/**
 * This makes sure that unloading the page requires user confirmation - if changesMade is true.
 * Uses the browser's native `beforeunload` prevention feature.
 */
export function useUnloadConfirmation(changesMade: boolean): void {
    useEffect(() => {
        const beforeUnloadHandler = (e: BeforeUnloadEvent): void => {
            // Cancel the event to show unsaved changes dialog
            e.preventDefault()
            e.returnValue = ''
        }
        if (changesMade) {
            window.addEventListener('beforeunload', beforeUnloadHandler)
            return () => window.removeEventListener('beforeunload', beforeUnloadHandler)
        }
    }, [changesMade])
}
