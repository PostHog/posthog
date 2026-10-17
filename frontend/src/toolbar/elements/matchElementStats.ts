import { collectAllElementsDeep } from 'query-selector-shadow-dom'

import {
    aggregateAndSortElements,
    buildDOMIndex,
    matchEventToElementUsingIndex,
    matchEventToElementUsingSelectors,
} from '~/toolbar/elements/domElementIndex'
import { CountedHTMLElement, ElementsEventType } from '~/toolbar/types'
import { elementIsVisible, trimElement } from '~/toolbar/utils'

/**
 * Matches element stats rows to the page's DOM in one pass, with the matchers the floating toolbar's clickmap
 * uses. The floating toolbar keeps its own incremental loop, because it yields, caches across refreshes and
 * reports match telemetry.
 */
export function matchElementStatsToElements(
    elementStats: ElementsEventType[],
    { dataAttributes, matchLinksByHref = false }: { dataAttributes: string[]; matchLinksByHref?: boolean }
): CountedHTMLElement[] {
    const pageElements = collectAllElementsDeep('*', document) as HTMLElement[]
    const domIndex = buildDOMIndex(pageElements)
    const selectorCache = new Map<string, HTMLElement[] | null>()
    const cursorPointerCache = new WeakMap<HTMLElement, boolean>()
    const visibilityCache = new WeakMap<HTMLElement, boolean>()

    const matchedElements: CountedHTMLElement[] = []
    for (const event of elementStats) {
        const matched =
            matchEventToElementUsingIndex(event, domIndex, { dataAttributes, matchLinksByHref }) ??
            matchEventToElementUsingSelectors(
                event,
                dataAttributes,
                matchLinksByHref,
                pageElements,
                selectorCache,
                domIndex.hasShadowRoots
            )
        if (!matched) {
            continue
        }
        const trimmed = trimElement(matched.element, { cursorPointerCache })
        if (trimmed && elementIsVisible(trimmed, visibilityCache)) {
            matchedElements.push({ ...matched, element: trimmed })
        }
    }
    return aggregateAndSortElements(matchedElements)
}
