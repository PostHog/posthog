import { useSyncExternalStore } from 'react'

let isPrinting = false

function subscribe(callback: () => void): () => void {
    const onBeforePrint = (): void => {
        isPrinting = true
        callback()
    }
    const onAfterPrint = (): void => {
        isPrinting = false
        callback()
    }
    window.addEventListener('beforeprint', onBeforePrint)
    window.addEventListener('afterprint', onAfterPrint)
    return () => {
        window.removeEventListener('beforeprint', onBeforePrint)
        window.removeEventListener('afterprint', onAfterPrint)
    }
}

/**
 * Returns true between the browser's `beforeprint` and `afterprint` events.
 * Use it to mount content that normally renders only on screen, so it is in the print snapshot.
 */
export function useIsPrinting(): boolean {
    return useSyncExternalStore(subscribe, () => isPrinting)
}
