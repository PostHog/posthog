import { matchesDataAttribute } from 'lib/actionUtils'

import { CountedHTMLElement, ElementsEventType } from '~/toolbar/types'
import { ElementType } from '~/types'

interface ElementFingerprint {
    tagName: string
    id: string | null
    classes: Set<string>
    dataAttrs: Map<string, string>
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
}

function addToIndex(map: Map<string, HTMLElement[]>, key: string, element: HTMLElement): void {
    const existing = map.get(key)
    if (existing) {
        existing.push(element)
    } else {
        map.set(key, [element])
    }
}

function createFingerprint(element: HTMLElement): ElementFingerprint {
    const parent = element.parentElement
    let nthChild = 1
    let nthOfType = 1

    if (parent) {
        const siblings = Array.from(parent.children)
        const elementIndex = siblings.indexOf(element)
        nthChild = elementIndex + 1
        nthOfType = siblings.filter((s, idx) => s.tagName === element.tagName && idx < elementIndex).length + 1
    }

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

export function buildDOMIndex(pageElements: HTMLElement[]): DOMIndex {
    const index: DOMIndex = {
        byId: new Map(),
        byTagName: new Map(),
        byClass: new Map(),
        byDataAttr: new Map(),
        byHref: new Map(),
        fingerprints: new WeakMap(),
    }

    for (const element of pageElements) {
        const fingerprint = createFingerprint(element)
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

function getCandidatesFromIndex(
    eventElement: ElementType,
    dataAttributes: string[],
    matchLinksByHref: boolean,
    index: DOMIndex
): HTMLElement[] {
    const matchedAttr = matchesDataAttribute(eventElement, dataAttributes)
    if (matchedAttr && eventElement.attributes) {
        const value = eventElement.attributes[`attr__${matchedAttr}`]
        if (value !== undefined) {
            const candidates = index.byDataAttr.get(matchedAttr)?.get(value) || []
            if (candidates.length) {
                return candidates.filter((el) => {
                    const fp = index.fingerprints.get(el)
                    return fp && matchesPosition(fp, eventElement)
                })
            }
        }
    }

    if (eventElement.attr_id) {
        const candidates = index.byId.get(eventElement.attr_id) || []
        if (candidates.length) {
            return candidates.filter((el) => {
                const fp = index.fingerprints.get(el)
                return fp && matchesPosition(fp, eventElement)
            })
        }
    }

    let candidates = eventElement.tag_name ? [...(index.byTagName.get(eventElement.tag_name.toLowerCase()) || [])] : []

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

    return candidates.filter((el) => {
        const fp = index.fingerprints.get(el)
        return fp && matchesPosition(fp, eventElement)
    })
}

function matchesParent(candidate: HTMLElement, parentEvent: ElementType, index: DOMIndex): boolean {
    const parent = candidate.parentElement
    if (!parent) {
        return false
    }

    const fp = index.fingerprints.get(parent)
    if (!fp) {
        return false
    }

    if (parentEvent.tag_name && fp.tagName !== parentEvent.tag_name.toLowerCase()) {
        return false
    }
    if (parentEvent.attr_id && fp.id !== parentEvent.attr_id) {
        return false
    }
    if (parentEvent.attr_class?.length) {
        for (const cls of parentEvent.attr_class) {
            if (cls && !fp.classes.has(cls)) {
                return false
            }
        }
    }
    return true
}

function isTooSimple(element: ElementType): boolean {
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

export function matchEventToElementUsingIndex(
    event: ElementsEventType,
    dataAttributes: string[],
    matchLinksByHref: boolean,
    index: DOMIndex
): CountedHTMLElement | null {
    const targetElement = event.elements[0]
    if (!targetElement) {
        return null
    }

    let candidates = getCandidatesFromIndex(targetElement, dataAttributes, matchLinksByHref, index)

    if (candidates.length === 0) {
        return null
    }

    for (let i = 1; i < event.elements.length && candidates.length > 1; i++) {
        candidates = candidates.filter((c) => matchesParent(c, event.elements[i], index))
    }

    if (candidates.length === 1 && !isTooSimple(targetElement)) {
        return {
            element: candidates[0],
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
