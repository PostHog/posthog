import { querySelectorAllDeep } from 'query-selector-shadow-dom'

import { TAGS_TO_IGNORE } from 'lib/actionUtils'

import { TOOLBAR_ID, elementIsVisible, getParent, getSafeText } from '~/toolbar/utils'

export interface SelectorGroup {
    cardinality: number
    cssSelectors: Array<{
        css: string
        offset: number
    }>
}

export interface AutoData {
    notextGroups: SelectorGroup[]
    textGroups: SelectorGroup[]
}

export interface InferredSelector {
    autoData: string
    text: string | null
    excludeText?: boolean
}

export interface InferenceResult {
    element: HTMLElement
    selector: InferredSelector
}

export interface InferenceConfig {
    inferenceAttributeNames: string[]
    inferenceAttributeFilters: Record<string, Array<(value: string) => boolean>>
    inferenceClassNameFilters: Array<(className: string) => boolean>
    maxCardinality: number
    maxAncestorSelectors: number
}

export const DEFAULT_INFERENCE_CONFIG: InferenceConfig = {
    inferenceAttributeNames: [
        // only look for these attributes
        'data-attr',
        'data-testid',
        'data-test-id',
        'data-cy',
        'data-ph',
        'id',
        'name',
        'placeholder',
        'role',
        'aria-label',
        'data-id',
    ],
    inferenceAttributeFilters: {
        // exclude IDs that end in digits, likely auto-generated
        id: [(value) => !/\d$/.test(value)],
        'data-id': [(value) => !/\d$/.test(value)],
    },
    inferenceClassNameFilters: [
        // exclude classnames that are probably css-in-js
        (cls) => !cls.startsWith('css-'),
        (cls) => !cls.startsWith('sc-'),
        (cls) => !/^[a-zA-Z]{1,3}[0-9a-zA-Z]{5,}$/.test(cls),
        (cls) => !cls.includes('[') && !cls.includes(']'),
    ],
    maxCardinality: 100, // skip selectors matching >100 elements (too vague)
    maxAncestorSelectors: 20, // go up max 20 ancestors
}

// get all valid selectors for a given element
function getOwnSelectors(element: HTMLElement, config: InferenceConfig): string[] {
    const selectors: string[] = []

    // find all allowlisted attributes
    for (const attrName of config.inferenceAttributeNames) {
        const value = element.getAttribute(attrName)
        if (!value) {
            continue
        }

        const filters = config.inferenceAttributeFilters[attrName]
        if (filters && !filters.every((filter) => filter(value))) {
            continue
        }

        // handle 'special' attribute cases (just `id` for now)
        // could also only do `tag[attr=val]` for cases where attrName is name, placeholder, etc
        if (attrName === 'id') {
            selectors.push(`#${CSS.escape(value)}`)
        } else {
            selectors.push(`[${attrName}="${CSS.escape(value)}"]`)
        }
    }

    // add valid classnames
    element.classList.forEach((cls) => {
        const passesFilters = config.inferenceClassNameFilters.every((filter) => filter(cls))
        if (passesFilters && cls.trim()) {
            selectors.push(`.${CSS.escape(cls)}`)
        }
    })

    return selectors
}

// collect selectors for target element's ancestors
function getAncestorSelectors(element: HTMLElement, config: InferenceConfig): Array<string | null> {
    // build map of selector -> # matches in the dom
    const selectorMap = new Map<string | null, number>()
    selectorMap.set(null, 0) // "no ancestor" option - 0 ensures it sorts first

    let parent = getParent(element)

    while (parent && parent.tagName !== 'BODY') {
        if (TAGS_TO_IGNORE.includes(parent.tagName.toLowerCase())) {
            parent = getParent(parent)
            continue
        }

        for (const selector of getOwnSelectors(parent, config)) {
            if (selectorMap.has(selector)) {
                continue
            }

            try {
                const matches = document.body.querySelectorAll(selector)
                selectorMap.set(selector, matches.length)
            } catch {
                console.warn('[ElementInference] Invalid selector during ancestor checks', selector, parent, element)
                continue
            }
        }
        parent = getParent(parent)
    }

    // sort by cardinality (ascending, lower = more specific), take top maxAncestorSelectors
    return Array.from(selectorMap.entries())
        .sort(([, a], [, b]) => a - b)
        .slice(0, config.maxAncestorSelectors)
        .map(([selector]) => selector)
}

// get element text - use getSafeText, but restrict to max 250 chars.
// anything higher -> prob not a good selector / button / target.
function getElementText(element: HTMLElement): string | null {
    const text = getSafeText(element)
    if (!text || text.length > 250) {
        return null
    }
    return text
}

function elementMatchesText(element: HTMLElement, text: string): boolean {
    const elementText = getElementText(element)
    return elementText?.toLowerCase() === text.toLowerCase()
}

// generator to query elements, filtering by text and visibility
function* queryElements(
    selector: string,
    text: string | null,
    visibilityCache: WeakMap<HTMLElement, boolean>
): Generator<HTMLElement, void, undefined> {
    let elements: NodeListOf<Element> | HTMLElement[]

    try {
        elements = querySelectorAllDeep(selector) as unknown as HTMLElement[]
    } catch {
        return
    }

    for (const el of elements) {
        const element = el as HTMLElement
        if (text && !elementMatchesText(element, text)) {
            continue
        }
        if (!elementIsVisible(element, visibilityCache)) {
            continue
        }
        yield element
    }
}

/**
 * this is the sauce, part 1
 *
 * builds a bunch of data about a given element for reliable lookup at runtime.
 *
 * it does this for a given target element (the thing the user clicked):
 * 1. make sure it's not in the toolbar lol
 * 2. get normalized element text
 * 3. get all possible selectors for the element
 * 4. get all possible selectors for the element's ancestors
 * 5. try all the combinations of self+ancestor selectors to see what matches
 * 6. for each combo that finds the target, record cardinality (how many matched) + offset (which one is ours)
 * 7. repeat step 6 but with text filtering
 * 8. sort the matches by cardinality (most specific first)
 */
export function inferSelector(
    element: HTMLElement,
    config: InferenceConfig = DEFAULT_INFERENCE_CONFIG
): InferenceResult | null {
    try {
        const toolbar = document.getElementById(TOOLBAR_ID)
        if (toolbar?.contains(element)) {
            return null
        }

        const text = getElementText(element)

        // build selector maps: cardinality -> [{css, offset}, ...]
        const notextMap = new Map<number, Array<{ css: string; offset: number }>>()
        const textMap = new Map<number, Array<{ css: string; offset: number }>>()

        const ownSelectors = [element.tagName.toLowerCase(), ...getOwnSelectors(element, config)]
        const ancestorSelectors = getAncestorSelectors(element, config)

        const visibilityCache = new WeakMap<HTMLElement, boolean>()

        const addToGroup = (
            map: Map<number, Array<{ css: string; offset: number }>>,
            cardinality: number,
            css: string,
            offset: number
        ): void => {
            if (offset < 0) {
                console.warn('[ElementInference] Element not found in its own selector matches', css, element)
                return
            }
            let group = map.get(cardinality)
            if (!group) {
                group = []
                map.set(cardinality, group)
            }
            group.push({ css, offset })
        }

        // test all combos of self + ancestor selectors
        for (const ownSelector of ownSelectors) {
            for (const ancestorSelector of ancestorSelectors) {
                const combined = ancestorSelector ? `${ancestorSelector} ${ownSelector}` : ownSelector

                // first, query w/o text filter.
                // user might have an element with dynamic text, otherwise
                // text-based matching is usually better
                const matches = Array.from(queryElements(combined, null, visibilityCache))
                const cardinality = matches.length

                // no matches or too many matches
                if (cardinality === 0 || cardinality > config.maxCardinality) {
                    continue
                }

                const offset = matches.indexOf(element)
                addToGroup(notextMap, cardinality, combined, offset)

                // repeat, but include text in the matching this time
                // ideally, this brings cardinality to 1
                if (text) {
                    const textMatches = Array.from(queryElements(combined, text, visibilityCache))
                    const textCardinality = textMatches.length
                    if (textCardinality > 0 && textCardinality <= config.maxCardinality) {
                        const textOffset = textMatches.indexOf(element)
                        addToGroup(textMap, textCardinality, combined, textOffset)
                    }
                }
            }
        }

        if (notextMap.size === 0 && textMap.size === 0) {
            console.warn('[ElementInference] No selectors found for element', element)
            return null
        }

        const toGroups = (map: Map<number, Array<{ css: string; offset: number }>>): SelectorGroup[] => {
            return Array.from(map.entries())
                .map(([cardinality, cssSelectors]) => ({ cardinality, cssSelectors }))
                .sort((a, b) => a.cardinality - b.cardinality)
        }

        // build "autodata" -> all the selectors we found, with their cardinality
        const autoData: AutoData = {
            notextGroups: toGroups(notextMap),
            textGroups: toGroups(textMap),
        }

        // the sauce is ready to be served
        return {
            element,
            selector: {
                autoData: JSON.stringify(autoData),
                text,
            },
        }
    } catch (error) {
        console.error('[ElementInference] Error inferring selector:', error)
        return null
    }
}

// could be inlined, but wanna keep lazy eval from queryElements
function nth<T>(iterable: Iterable<T>, n: number): T | null {
    let idx = 0
    for (const item of iterable) {
        if (idx === n) {
            return item
        }
        idx++
    }
    return null
}

/**
 * if inferSelector is the sauce, this is the nugget
 *
 * find an element in the dom using the element inference data
 *
 * 1. try each group of selectors, starting with most specific (lowest cardinality)
 * 2. try each selector in the group - run the css query, go to offset
 * 3. "vote" for the element if it was found
 * 4. return early if any element gets majority votes
 * 5. return element w/ most votes
 */
export function findElement(selector: InferredSelector): HTMLElement | null {
    try {
        const autoData: AutoData = JSON.parse(selector.autoData)
        const { text, excludeText } = selector

        // excludeText -> user setting, usually if the target element
        // has dynamic/localized text
        const useText = text != null && !excludeText

        // choose appropriate group + sort
        const groups = (useText ? autoData.textGroups : autoData.notextGroups).sort(
            (a, b) => a.cardinality - b.cardinality
        )

        if (groups.length === 0) {
            return null
        }

        const visibilityCache = new WeakMap<HTMLElement, boolean>()

        // try each selector group, starting w/ most specific (lowest cardinality)
        for (const group of groups) {
            const votes = new Map<HTMLElement, number>()
            let winner: HTMLElement | null = null
            let maxVotes = 0

            // test each selector in the group
            for (const { css, offset } of group.cssSelectors) {
                // get matches, jump to offset to find our target
                const element = nth(queryElements(css, useText ? text : null, visibilityCache), offset)

                if (!element) {
                    continue
                }

                // if we found something, this element gets a vote
                const voteCount = (votes.get(element) ?? 0) + 1
                votes.set(element, voteCount)

                if (voteCount > maxVotes) {
                    maxVotes = voteCount
                    winner = element

                    // break early if we have a majority
                    if (voteCount >= Math.ceil(group.cssSelectors.length / 2)) {
                        return winner
                    }
                }
            }

            if (winner) {
                return winner
            }
        }

        return null
    } catch (error) {
        console.error('[ElementInference] Error finding element:', error)
        return null
    }
}

export function getElementPath(el: HTMLElement | null, depth = 4): string | null {
    if (!el) {
        return null
    }
    const parts: string[] = []
    let current: HTMLElement | null = el

    while (current && parts.length < depth && current.tagName !== 'BODY') {
        let part = current.tagName.toLowerCase()
        if (current.id) {
            part += `#${current.id}`
        } else if (current.classList.length) {
            part += `.${current.classList[0]}`
        }
        parts.unshift(part)
        current = current.parentElement
    }

    return parts.join(' > ')
}

export function parseAutoData(selector: InferredSelector): AutoData {
    return JSON.parse(selector.autoData)
}

export function testInference(
    element: HTMLElement,
    config?: InferenceConfig
): {
    success: boolean
    inferenceResult: InferenceResult | null
    foundElement: HTMLElement | null
    match: boolean
} {
    const inferenceResult = inferSelector(element, config)

    if (!inferenceResult) {
        return { success: false, inferenceResult: null, foundElement: null, match: false }
    }

    const foundElement = findElement(inferenceResult.selector)

    return {
        success: true,
        inferenceResult,
        foundElement,
        match: foundElement === element,
    }
}

// add to window for testing :)
if (typeof window !== 'undefined') {
    ;(window as any).__posthogElementInference = {
        inferSelector,
        findElement,
        parseAutoData,
        testInference,
        DEFAULT_INFERENCE_CONFIG,
    }
}
