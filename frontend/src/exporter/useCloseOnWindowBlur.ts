import { useEffect } from 'react'

/**
 * A click inside the sandboxed canvas never reaches this document, but focus moving into the iframe blurs
 * the window, which is the only signal the page gets to close an open menu.
 */
export function useCloseOnWindowBlur(open: boolean, onClose: () => void): void {
    useEffect(() => {
        if (!open) {
            return
        }
        window.addEventListener('blur', onClose)
        return () => window.removeEventListener('blur', onClose)
    }, [open, onClose])
}
