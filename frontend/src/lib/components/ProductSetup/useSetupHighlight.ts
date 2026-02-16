import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { globalSetupLogic } from './globalSetupLogic'

const HIGHLIGHT_CLASS = 'setup-highlight-pulse'
const HIGHLIGHT_DURATION_MS = 3000
const MAX_ATTEMPTS = 30
const ATTEMPT_INTERVAL_MS = 200

/**
 * Find the closest scrollable ancestor of an element.
 */
function getScrollableAncestor(element: Element): HTMLElement | null {
    let current = element.parentElement

    while (current && current !== document.documentElement) {
        const style = window.getComputedStyle(current)
        const overflowY = style.overflowY

        if ((overflowY === 'auto' || overflowY === 'scroll') && current.scrollHeight > current.clientHeight) {
            return current
        }

        current = current.parentElement
    }

    return null
}

/**
 * Scroll an element into view within its scrollable container, without affecting
 * any parent scroll positions. This prevents Chrome from scrolling the entire
 * viewport when scrolling nested containers.
 */
function scrollIntoViewWithinContainer(element: Element): void {
    const scrollContainer = getScrollableAncestor(element)
    if (!scrollContainer) {
        return
    }

    // Capture scroll positions of ALL ancestors before scrolling
    const scrollPositions: Array<{ element: Element; top: number; left: number }> = []
    let ancestor: Element | null = scrollContainer.parentElement
    while (ancestor) {
        scrollPositions.push({
            element: ancestor,
            top: ancestor.scrollTop,
            left: ancestor.scrollLeft,
        })
        ancestor = ancestor.parentElement
    }
    // Also capture window scroll
    const windowScrollX = window.scrollX
    const windowScrollY = window.scrollY

    // Scroll the target container
    const elementRect = element.getBoundingClientRect()
    const containerRect = scrollContainer.getBoundingClientRect()
    const elementTop = elementRect.top - containerRect.top + scrollContainer.scrollTop
    const targetScroll = elementTop - containerRect.height / 2 + elementRect.height / 2
    scrollContainer.scrollTo({ top: Math.max(0, targetScroll), behavior: 'smooth' })

    // Restore all ancestor scroll positions immediately
    for (const { element: el, top, left } of scrollPositions) {
        if (el.scrollTop !== top || el.scrollLeft !== left) {
            el.scrollTop = top
            el.scrollLeft = left
        }
    }
    // Restore window scroll
    if (window.scrollX !== windowScrollX || window.scrollY !== windowScrollY) {
        window.scrollTo(windowScrollX, windowScrollY)
    }
}

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
    const highlightedElementRef = useRef<Element | null>(null)

    useEffect(() => {
        if (!highlightSelector) {
            return
        }

        attemptCountRef.current = 0

        const tryHighlight = (): void => {
            const element = document.querySelector(highlightSelector)

            if (element) {
                // Found the element - apply highlight
                highlightedElementRef.current = element
                element.classList.add(HIGHLIGHT_CLASS)

                // Scroll within the correct container without affecting parent scroll
                scrollIntoViewWithinContainer(element)

                // Remove highlight after duration
                timeoutRef.current = setTimeout(() => {
                    element.classList.remove(HIGHLIGHT_CLASS)
                    highlightedElementRef.current = null
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
        timeoutRef.current = setTimeout(tryHighlight, 150)

        return () => {
            if (timeoutRef.current) {
                clearTimeout(timeoutRef.current)
            }
            // Clean up highlighted element if component unmounts
            if (highlightedElementRef.current) {
                highlightedElementRef.current.classList.remove(HIGHLIGHT_CLASS)
                highlightedElementRef.current = null
            }
        }
    }, [highlightSelector, clearHighlightSelector])
}
