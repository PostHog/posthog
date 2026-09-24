import { querySelectorAllDeep } from 'query-selector-shadow-dom'

import { elementToSelector, matchesDataAttribute } from 'lib/utils/actions'

import { toolbarLogger } from '~/toolbar/toolbarLogger'
import { CountedHTMLElement, ElementsEventType } from '~/toolbar/types'
import { TOOLBAR_ID } from '~/toolbar/utils'
import { ElementType } from '~/types'

interface ElementFingerprint {
    tagName: string
    id: string | null
    classes: Set<string>
    dataAttrs: Map<string, string>
    nthChild: number
    nthOfType: number
}

interface ElementPosition {
    nthChild: number
    nthOfType: number
}

export interface DOMIndex {
    byId: Map<string, HTMLElement[]>
    byTagName: Map<string, HTMLElement[]>
    byClass: Map<string, HTMLElement[]>
    byDataAttr: Map<string, Map<string, HTMLElement[]>>
    byHref: Map<string, HTMLElement[]>
    fingerprints: WeakMap<HTMLElement, ElementFingerprint>
    hasShadowRoots: boolean
}

function addToIndex(map: Map<string, HTMLElement[]>, key: string, element: HTMLElement): void {
    const existing = map.get(key)
    if (existing) {
        existing.push(element)
    } else {
        map.set(key, [element])
    }
}

function getPosition(
    element: HTMLElement,
    positionsByParent: WeakMap<HTMLElement, Map<Element, ElementPosition>>
): ElementPosition {
    const parent = element.parentElement
    if (!parent) {
        return { nthChild: 1, nthOfType: 1 }
    }

    let positions = positionsByParent.get(parent)
    if (!positions) {
        positions = new Map()
        const typeCounts = new Map<string, number>()
        let nthChild = 0
        for (const child of Array.from(parent.children)) {
            nthChild += 1
            const nthOfType = (typeCounts.get(child.tagName) ?? 0) + 1
            typeCounts.set(child.tagName, nthOfType)
            positions.set(child, { nthChild, nthOfType })
        }
        positionsByParent.set(parent, positions)
    }
    return positions.get(element) ?? { nthChild: -1, nthOfType: -1 }
}

function createFingerprint(
    element: HTMLElement,
    positionsByParent: WeakMap<HTMLElement, Map<Element, ElementPosition>>
): ElementFingerprint {
    const { nthChild, nthOfType } = getPosition(element, positionsByParent)

    const dataAttrs = new Map<string, string>()
    for (let i = 0; i < element.attributes.length; i++) {
        const attr = element.attributes[i]
        if (attr.name.startsWith('data-')) {
            dataAttrs.set(attr.name, attr.value)
        }
    }

    return {
        tagName: element.tagName.toLowerCase(),
        id: element.id || null,
        classes: new Set(Array.from(element.classList)),
        dataAttrs,
        nthChild,
        nthOfType,
    }
}

export function hasNonToolbarShadowRoots(pageElements: HTMLElement[]): boolean {
    return pageElements.some((el) => !!el.shadowRoot && el.id !== TOOLBAR_ID)
}

export function buildDOMIndex(pageElements: HTMLElement[]): DOMIndex {
    const index: DOMIndex = {
        byId: new Map(),
        byTagName: new Map(),
        byClass: new Map(),
        byDataAttr: new Map(),
        byHref: new Map(),
        fingerprints: new WeakMap(),
        hasShadowRoots: false,
    }
    const positionsByParent = new WeakMap<HTMLElement, Map<Element, ElementPosition>>()

    for (const element of pageElements) {
        const fingerprint = createFingerprint(element, positionsByParent)
        index.fingerprints.set(element, fingerprint)

        if (fingerprint.id) {
            addToIndex(index.byId, fingerprint.id, element)
        }

        addToIndex(index.byTagName, fingerprint.tagName, element)

        for (const cls of fingerprint.classes) {
            addToIndex(index.byClass, cls, element)
        }

        for (const [name, value] of fingerprint.dataAttrs) {
            if (!index.byDataAttr.has(name)) {
                index.byDataAttr.set(name, new Map())
            }
            addToIndex(index.byDataAttr.get(name)!, value, element)
        }

        const href = element.getAttribute('href')
        if (href) {
            addToIndex(index.byHref, href, element)
        }

        if (element.shadowRoot && element.id !== TOOLBAR_ID) {
            index.hasShadowRoots = true
        }
    }

    return index
}

function matchesPosition(fingerprint: ElementFingerprint, eventElement: ElementType): boolean {
    if (eventElement.nth_child && fingerprint.nthChild !== eventElement.nth_child) {
        return false
    }
    if (eventElement.nth_of_type && fingerprint.nthOfType !== eventElement.nth_of_type) {
        return false
    }
    return true
}

function filterByPosition(candidates: HTMLElement[], eventElement: ElementType, index: DOMIndex): HTMLElement[] {
    return candidates.filter((el) => {
        const fp = index.fingerprints.get(el)
        return fp && matchesPosition(fp, eventElement)
    })
}

// position disambiguates siblings that share an identifier, but must not exclude a sole
// candidate (or all candidates) whose sibling position drifted since capture
function preferPositionMatches(candidates: HTMLElement[], eventElement: ElementType, index: DOMIndex): HTMLElement[] {
    if (candidates.length <= 1) {
        return candidates
    }
    const positioned = filterByPosition(candidates, eventElement, index)
    return positioned.length ? positioned : candidates
}

// derived once per chain level, not per candidate: matchesDataAttribute builds a RegExp per call
function getMatchedDataAttribute(
    eventElement: ElementType,
    dataAttributes: string[]
): { name: string; value: string } | null {
    const matchedAttr = matchesDataAttribute(eventElement, dataAttributes)
    if (!matchedAttr) {
        return null
    }
    const value = eventElement.attributes?.[`attr__${matchedAttr}`]
    return value === undefined ? null : { name: matchedAttr, value }
}

function getCandidatesFromIndex(
    eventElement: ElementType,
    dataAttributes: string[],
    matchLinksByHref: boolean,
    index: DOMIndex
): HTMLElement[] {
    // a configured data attribute or an id identifies the element on its own — mirroring
    // elementToSelector, which early-returns on these — so sibling-position drift from injected
    // DOM must not exclude a uniquely identified candidate; position still breaks ties between
    // siblings that share the identifier
    const matchedDataAttribute = getMatchedDataAttribute(eventElement, dataAttributes)
    if (matchedDataAttribute) {
        const candidates = index.byDataAttr.get(matchedDataAttribute.name)?.get(matchedDataAttribute.value) || []
        if (candidates.length) {
            return preferPositionMatches(candidates, eventElement, index)
        }
    }

    if (eventElement.attr_id) {
        const candidates = index.byId.get(eventElement.attr_id) || []
        if (candidates.length) {
            return preferPositionMatches(candidates, eventElement, index)
        }
    }

    let candidates = eventElement.tag_name ? index.byTagName.get(eventElement.tag_name.toLowerCase()) || [] : []

    if (eventElement.attr_class?.length) {
        for (const cls of eventElement.attr_class) {
            if (cls) {
                const classMatches = new Set(index.byClass.get(cls) || [])
                candidates = candidates.filter((el) => classMatches.has(el))
            }
        }
    }

    if (matchLinksByHref && eventElement.href) {
        const hrefMatches = new Set(index.byHref.get(eventElement.href) || [])
        candidates = candidates.filter((el) => hrefMatches.has(el))
    }

    return filterByPosition(candidates, eventElement, index)
}

function fingerprintMatchesEventElement(
    fingerprint: ElementFingerprint | undefined,
    eventElement: ElementType,
    matchedDataAttribute: { name: string; value: string } | null
): boolean {
    if (!fingerprint) {
        return false
    }
    if (eventElement.tag_name && fingerprint.tagName !== eventElement.tag_name.toLowerCase()) {
        return false
    }
    if (eventElement.attr_id && fingerprint.id !== eventElement.attr_id) {
        return false
    }
    for (const cls of eventElement.attr_class ?? []) {
        if (cls && !fingerprint.classes.has(cls)) {
            return false
        }
    }
    // an id or configured data attribute identifies the ancestor on its own, so DOM drift that
    // shifts sibling positions (cookie banners, injected wrappers) shouldn't kill the match —
    // mirroring elementToSelector, which early-returns on these without position; the id guard
    // above already established id equality
    const identifiedWithoutPosition =
        !!eventElement.attr_id ||
        (!!matchedDataAttribute && fingerprint.dataAttrs.get(matchedDataAttribute.name) === matchedDataAttribute.value)
    return identifiedWithoutPosition || matchesPosition(fingerprint, eventElement)
}

const normalizeText = (text: string | null | undefined): string => (text ?? '').replace(/\s+/g, ' ').trim()

function textCompatible(capturedText: string, element: HTMLElement): boolean {
    const live = normalizeText(element.textContent)
    if (!live) {
        return true
    }
    return capturedText === live || capturedText.startsWith(live) || live.startsWith(capturedText)
}

function hrefCompatible(element: HTMLElement, eventElement: ElementType): boolean {
    return !eventElement.href || element.getAttribute('href') === eventElement.href
}

function discriminateCandidates(
    candidates: HTMLElement[],
    eventElement: ElementType,
    capturedText: string
): HTMLElement[] {
    let remaining = candidates
    if (remaining.length > 1 && eventElement.href) {
        const byHref = remaining.filter((element) => hrefCompatible(element, eventElement))
        if (byHref.length) {
            remaining = byHref
        }
    }
    if (remaining.length > 1 && capturedText) {
        const byText = remaining.filter((element) => textCompatible(capturedText, element))
        if (byText.length === 1) {
            remaining = byText
        }
    }
    return remaining
}

function resolveMatchedElement(
    walkers: { candidate: HTMLElement }[],
    candidates: HTMLElement[],
    eventElement: ElementType,
    useDiscriminators: boolean
): HTMLElement | null {
    const chainMatch = walkers.length === 1 ? walkers[0].candidate : null
    if (!useDiscriminators) {
        return chainMatch
    }
    const capturedText = normalizeText(eventElement.text)
    if (
        chainMatch &&
        hrefCompatible(chainMatch, eventElement) &&
        (!capturedText || textCompatible(capturedText, chainMatch))
    ) {
        return chainMatch
    }
    const pool = walkers.length > 1 ? walkers.map((walker) => walker.candidate) : candidates
    const narrowed = discriminateCandidates(pool, eventElement, capturedText)
    return narrowed.length === 1 ? narrowed[0] : null
}

function liveNodeMatchesLevel(node: HTMLElement, level: ElementType, index: DOMIndex): boolean {
    const fingerprint = index.fingerprints.get(node)
    if (level.tag_name && (fingerprint?.tagName ?? node.tagName.toLowerCase()) !== level.tag_name.toLowerCase()) {
        return false
    }
    if (level.attr_id && node.id !== level.attr_id) {
        return false
    }
    return !fingerprint || !node.parentElement || matchesPosition(fingerprint, level)
}

export function matchIsChainConsistent(element: HTMLElement, chain: ElementType[], index: DOMIndex): boolean {
    let node: HTMLElement | null = element
    for (const level of chain) {
        if (!node || !liveNodeMatchesLevel(node, level, index)) {
            return false
        }
        node = node.parentElement
    }
    return true
}

export function chainConsistencyProperties(counts: {
    useDiscriminators: boolean
    consistentClicks: number
    inconsistentClicks: number
    matchedClicks: number
    totalClicks: number
}): Record<string, boolean | number> {
    return {
        discriminators_enabled: counts.useDiscriminators,
        consistent_click_count: counts.consistentClicks,
        inconsistent_click_count: counts.inconsistentClicks,
        matched_click_count: counts.matchedClicks,
        total_click_count: counts.totalClicks,
    }
}

export function isTooSimple(element: ElementType): boolean {
    return !!(
        element.tag_name &&
        !element.attr_class &&
        !element.attr_id &&
        !element.href &&
        !element.text &&
        element.nth_child === 1 &&
        element.nth_of_type === 1 &&
        !element.attributes?.['attr__data-attr']
    )
}

export interface ElementMatchOptions {
    dataAttributes?: string[]
    matchLinksByHref?: boolean
    useDiscriminators?: boolean
}

export function matchEventToElementUsingIndex(
    event: ElementsEventType,
    index: DOMIndex,
    { dataAttributes = [], matchLinksByHref = false, useDiscriminators = false }: ElementMatchOptions = {}
): CountedHTMLElement | null {
    const targetElement = event.elements[0]
    if (!targetElement) {
        return null
    }

    const candidates = getCandidatesFromIndex(targetElement, dataAttributes, matchLinksByHref, index)

    if (candidates.length === 0) {
        return null
    }

    let walkers = candidates.map((candidate) => ({ candidate, ancestor: candidate.parentElement }))
    for (let i = 1; i < event.elements.length && walkers.length > 1; i++) {
        const eventAncestor = event.elements[i]
        const ancestorDataAttribute = getMatchedDataAttribute(eventAncestor, dataAttributes)
        walkers = walkers.flatMap(({ candidate, ancestor }) => {
            if (
                !ancestor ||
                !fingerprintMatchesEventElement(index.fingerprints.get(ancestor), eventAncestor, ancestorDataAttribute)
            ) {
                return []
            }
            return [{ candidate, ancestor: ancestor.parentElement }]
        })
    }

    const resolved = resolveMatchedElement(walkers, candidates, targetElement, useDiscriminators)

    if (resolved && !isTooSimple(targetElement)) {
        return {
            element: resolved,
            count: event.count,
            selector: '',
            hash: event.hash,
            type: event.type,
            clickCount: 0,
            rageclickCount: 0,
            deadclickCount: 0,
        }
    }

    return null
}

// each chain level costs a selector query, so a single deep-chain event (legitimately deep DOM or a
// forged chain) could otherwise hold the main thread for an unbounded uninterruptible stretch
const MAX_SELECTOR_CHAIN_LEVELS = 10

export function matchEventToElementUsingSelectors(
    event: ElementsEventType,
    dataAttributes: string[],
    matchLinksByHref: boolean,
    pageElements: HTMLElement[],
    selectorCache: Map<string, HTMLElement[] | null>,
    hasShadowRoots: boolean
): CountedHTMLElement | null {
    let lastSelector: string | undefined

    const chainDepth = Math.min(event.elements.length, MAX_SELECTOR_CHAIN_LEVELS)
    for (let i = 0; i < chainDepth; i++) {
        const element = event.elements[i]
        const selector =
            elementToSelector(matchLinksByHref ? element : { ...element, href: undefined }, dataAttributes) || '*'
        const combinedSelector = lastSelector ? `${selector} > ${lastSelector}` : selector

        // null marks a selector that previously threw — repeat encounters bail out exactly like
        // the original failure did
        let domElements = selectorCache.get(combinedSelector)
        if (domElements === null) {
            break
        }

        try {
            if (domElements === undefined) {
                domElements = hasShadowRoots
                    ? Array.from(querySelectorAllDeep(combinedSelector, document, pageElements))
                    : Array.from(document.querySelectorAll<HTMLElement>(combinedSelector))
                selectorCache.set(combinedSelector, domElements)
            }

            if (domElements.length === 1) {
                const firstAndTooSimple = i === 0 && isTooSimple(event.elements[i])
                if (!firstAndTooSimple) {
                    return {
                        element: domElements[0],
                        count: event.count,
                        selector: selector,
                        hash: event.hash,
                        type: event.type,
                        clickCount: 0,
                        rageclickCount: 0,
                        deadclickCount: 0,
                    }
                }
            }

            if (domElements.length === 0) {
                if (i === event.elements.length - 1) {
                    return null
                } else if (i > 0 && lastSelector) {
                    lastSelector = `* > ${lastSelector}`
                    continue
                }
            }
        } catch {
            // sentinel-cache the failing selector so repeated rows neither re-throw nor re-log,
            // and truncate: event-derived selectors can embed long customer-page attribute values
            selectorCache.set(combinedSelector, null)
            toolbarLogger.warn('heatmap', 'Failed to resolve heatmap element with selector', {
                selector: combinedSelector.slice(0, 200),
            })
            break
        }

        lastSelector = combinedSelector
    }

    return null
}
