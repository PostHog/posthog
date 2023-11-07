import { ElementType } from '~/types'

export type ParsedCSSSelector = Record<string, string | string[] | undefined>

export const parsedSelectorToSelectorString = (parsedSelector: ParsedCSSSelector): string => {
    const attributeSelectors = Object.entries(parsedSelector).reduce((acc, [key, value]) => {
        if (!!value && key !== 'tag' && key !== 'text' && key !== 'id') {
            if (key === 'class') {
                if (!Array.isArray(value)) {
                    throw new Error(`Was expecting an array here. Attribute: ${key} has a string value: ${value}`)
                } else if (value.length > 0) {
                    acc.push(`.${Array.from(value).join('.')}`)
                }
            } else if (key === 'combinator') {
                acc.push(`${value}`)
            } else {
                if (Array.isArray(value)) {
                    throw new Error(
                        `Not expecting an array here. Attribute: ${key} has an array value: ${value.join(', ')}`
                    )
                } else {
                    acc.push(`[${key}="${value}"]`)
                }
            }
        }
        return acc
    }, [] as string[])

    const tagSelector = parsedSelector.tag ? parsedSelector.tag : ''
    const idSelector = parsedSelector.id ? `[id="${parsedSelector.id}"]` : ''
    const builtSelector = `${tagSelector}${idSelector}${attributeSelectors.join('')}`
    return builtSelector
}

export const parseCSSSelector = (s: string): ParsedCSSSelector => {
    const parts = {} as ParsedCSSSelector
    let processing: string | undefined = undefined
    let attributeKey = ''
    let current = ''

    function closeItem(): void {
        if (current.length > 0 && processing) {
            const existing = parts[processing]
            if (existing || processing === 'class') {
                if (Array.isArray(existing)) {
                    existing.push(current)
                } else {
                    parts[processing] = [existing, current].filter((x) => !!x) as string[]
                }
            } else {
                parts[processing] = current
            }
            current = ''
        }
    }

    // processing things with a grammar like html and css with regex is a route to madness
    // pulling in a library like parsel is taking on a new dependency for a hopefully limited use case
    // we don't need to support all the css selectors,
    // so, we'll just do it manually (until we need the new dependency)
    Array.from(s).forEach((char) => {
        if (char === '#') {
            closeItem()
            processing = 'id'
        } else if (char === '>' && processing === undefined) {
            processing = 'combinator'
            current = char
            closeItem()
        } else if ([':', '+'].includes(char)) {
            closeItem()
            processing = 'ignore'
        } else if (char === '.') {
            closeItem()
            // don't add the dot to the class
            processing = 'class'
        } else if (char === '[') {
            closeItem()
            processing = 'key'
        } else if (processing === 'key' && char === '=') {
            attributeKey = current
            current = ''
            processing = 'value'
        } else if (processing === 'value' && char === ']') {
            parts[attributeKey] = current
            current = ''
            processing = undefined
        } else if (processing === 'value' && char === '"') {
            // ignore
        } else {
            current += char
            if (processing === undefined) {
                processing = 'tag'
            }
        }
    })

    if (current.length > 0 && processing) {
        closeItem()
    }

    delete parts.ignore
    return parts
}

export const matchesSelector = (e: ElementType, s: ParsedCSSSelector): boolean => {
    const selectorKeysMatch = [] as boolean[]
    Object.keys(s).forEach((key) => {
        if (key === 'combinator') {
            // combinators come on their own and can never match an element
            selectorKeysMatch.push(false)
        } else if (key === 'tag' && s.tag && s.tag === e.tag_name) {
            selectorKeysMatch.push(true)
        } else if (key === 'id' && s.id && e.attr_id && s.id === e.attr_id) {
            selectorKeysMatch.push(true)
        } else {
            // s.class is a string or a string[]
            const val: string | string[] | undefined = s[key]
            if (val) {
                const keysToMatch: string[] | undefined = Array.isArray(val) ? val : [val]
                // it matches if every item in s[key] is in e.attributes[key]
                if (
                    !!keysToMatch &&
                    keysToMatch.every((c) => {
                        const haystack =
                            e.attributes && e.attributes?.[key] ? e.attributes[key] : e.attributes?.[`attr__${key}`]
                        return c && !!haystack && haystack?.includes(c)
                    })
                ) {
                    selectorKeysMatch.push(true)
                }
            }
        }
    })

    return selectorKeysMatch.length >= Object.keys(s).length && selectorKeysMatch.every((m) => m)
}

export function preselect(elements: ElementType[], autoSelector: string): Record<number, ParsedCSSSelector> {
    const selectors = autoSelector
        .split(' ')
        .map((selector) => {
            // don't need to support things like :nth-child(1) or :nth-child(2)
            return selector.split(':')[0]
        })
        .map((selector) => {
            return parseCSSSelector(selector)
        })

    const selections = {} as Record<number, Record<string, string | string[] | undefined>>

    // we compare the list of selectors with the list of elements
    // naively we'd just loop through the elements and check if they match the selector
    // but, the element index does not necessarily monotonically increase
    // we need to support child combinators, so we need to keep track of the last match
    // if we start to match and then a child combinator means we have matched prematurely
    // we delete the premature match and start again from the last match
    let selectorIndex = 0
    let lastMatchedSelectorIndex = -1 // if we have a combinator, this is the match that might be invalidated
    let lastMatchedIndex = -1 // if we have a combinator, this is the match that might be invalidated
    let mustMatchAtNextIndex = false // if we have a combinator, we need to match the next selector at this elementIndex
    let nextSelector = selectors[selectorIndex]
    let elementIndex = 0
    while (elementIndex < elements.length) {
        const el = elements[elementIndex]
        if (selectorIndex >= selectors.length) {
            break
        } else {
            nextSelector = selectors[selectorIndex]
        }

        if (nextSelector.combinator === '>') {
            mustMatchAtNextIndex = true
            selectorIndex++
        } else if (matchesSelector(el, nextSelector)) {
            selections[elementIndex] = nextSelector
            lastMatchedIndex = elementIndex
            lastMatchedSelectorIndex = selectorIndex
            mustMatchAtNextIndex = false
            selectorIndex++
            elementIndex++
        } else {
            if (mustMatchAtNextIndex) {
                // failed to match after a child combinator
                // reset to the last match
                selectorIndex = lastMatchedSelectorIndex
                delete selections[lastMatchedIndex]
                elementIndex = lastMatchedIndex + 1
                mustMatchAtNextIndex = false
            } else {
                elementIndex++
            }
        }
    }

    return selections
}
