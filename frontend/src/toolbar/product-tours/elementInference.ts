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
