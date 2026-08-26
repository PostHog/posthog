import './questionHighlight.scss'

import { RefObject, useEffect } from 'react'

import { findQuestionRanges } from './questionRanges'

const HIGHLIGHT_NAME = 'support-question'
const CUSTOMER_MESSAGE = '[data-message-author="customer"]'

export function supportsQuestionHighlight(): boolean {
    return typeof CSS !== 'undefined' && 'highlights' in CSS
}

/**
 * Tints every question sentence in the customer messages under `containerRef`.
 *
 * One registry entry is shared, so only one panel may have this on at a time.
 */
export function useQuestionHighlight<T extends HTMLElement>(containerRef: RefObject<T | null>, enabled: boolean): void {
    useEffect(() => {
        const container = containerRef.current
        if (!enabled || !container || !supportsQuestionHighlight()) {
            return
        }

        let frame: number | null = null

        const apply = (): void => {
            frame = null
            const ranges = Array.from(container.querySelectorAll<HTMLElement>(CUSTOMER_MESSAGE)).flatMap((message) =>
                findQuestionRanges(message)
            )
            if (ranges.length > 0) {
                CSS.highlights.set(HIGHLIGHT_NAME, new Highlight(...ranges))
            } else {
                CSS.highlights.delete(HIGHLIGHT_NAME)
            }
        }

        const schedule = (): void => {
            if (frame === null) {
                frame = requestAnimationFrame(apply)
            }
        }

        // The thread fills in after it mounts — TipTap sets each message's content on its own, and the poll
        // appends replies — so watch the panel rather than guess which renders matter. This also rebuilds
        // the ranges when a node they point into is removed.
        const observer = new MutationObserver(schedule)
        observer.observe(container, { childList: true, characterData: true, subtree: true })
        apply()

        return () => {
            observer.disconnect()
            if (frame !== null) {
                cancelAnimationFrame(frame)
            }
            CSS.highlights.delete(HIGHLIGHT_NAME)
        }
    }, [containerRef, enabled])
}
