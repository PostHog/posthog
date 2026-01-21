import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { globalSetupLogic } from './globalSetupLogic'

const HIGHLIGHT_CLASS = 'setup-highlight-pulse'
const HIGHLIGHT_DURATION_MS = 5000
const MAX_ATTEMPTS = 20
const ATTEMPT_INTERVAL_MS = 200

/**
 * Hook that watches for a pending highlight selector and applies a pulsing
 * animation to the matching element. Used to draw attention to UI elements
 * after navigating from the quick start guide.
 *
 * Usage: Call this hook once in a top-level component (e.g., App or Layout).
 */
export function useSetupHighlight(): void {
    const { highlightSelector } = useValues(globalSetupLogic)
    const { clearHighlightSelector } = useActions(globalSetupLogic)
    const attemptCountRef = useRef(0)
    const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

    useEffect(() => {
        if (!highlightSelector) {
            return
        }

        attemptCountRef.current = 0

        const tryHighlight = (): void => {
            const element = document.querySelector(highlightSelector)

            if (element) {
                // Found the element - apply highlight
                element.classList.add(HIGHLIGHT_CLASS)
                element.scrollIntoView({ behavior: 'smooth', block: 'center' })

                // Remove highlight after duration
                timeoutRef.current = setTimeout(() => {
                    element.classList.remove(HIGHLIGHT_CLASS)
                    clearHighlightSelector()
                }, HIGHLIGHT_DURATION_MS)
            } else if (attemptCountRef.current < MAX_ATTEMPTS) {
                // Element not found yet - retry (it might still be rendering)
                attemptCountRef.current++
                timeoutRef.current = setTimeout(tryHighlight, ATTEMPT_INTERVAL_MS)
            } else {
                // Give up after max attempts
                clearHighlightSelector()
            }
        }

        // Start looking for the element after a short delay to allow navigation to complete
        timeoutRef.current = setTimeout(tryHighlight, 100)

        return () => {
            if (timeoutRef.current) {
                clearTimeout(timeoutRef.current)
            }
        }
    }, [highlightSelector, clearHighlightSelector])
}
