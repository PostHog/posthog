import { ElementType } from '~/types'

// nodejs/src/common/utils/elements-chain.ts reads the same grammar under RE2. The browser has no
// RE2, so every scan here is a single pass over client-supplied input that cannot backtrack.

const QUOTE = '"'
const ESCAPE = '\\'
const ELEMENT_SEPARATOR = ';'
const ATTRIBUTE_SEPARATOR = ':'
const WHITESPACE = /\s/
const ATTRIBUTE_KEY_CHARACTER = /[a-zA-Z0-9_-]/

/** Serializers escape only quotes, so a quote preceded by a backslash never closes a value. */
function findClosingQuote(text: string, valueStart: number): number {
    let position = valueStart
    while (true) {
        const closing = text.indexOf(QUOTE, position)
        if (closing === -1) {
            return -1
        }
        if (text[closing - 1] !== ESCAPE) {
            return closing
        }
        position = closing + 1
    }
}

/** A quote with no closing quote ends the element, unless the chain ends with an escaped quote. */
export function splitElementsChain(chain: string): string[] {
    const elements: string[] = []
    let tokenStart = -1
    let position = 0
    // A failed closing-quote search skipped every later quote as escaped, so later searches fail too.
    let closingQuotesRemain = true

    const endToken = (end: number): void => {
        if (tokenStart !== -1 && end > tokenStart) {
            elements.push(chain.slice(tokenStart, end))
        }
        tokenStart = -1
    }

    while (position < chain.length) {
        const character = chain[position]
        if (character === QUOTE) {
            let closing = closingQuotesRemain ? findClosingQuote(chain, position + 1) : -1
            if (closing === -1 && chain.length - 1 > position && chain.endsWith(ESCAPE + QUOTE)) {
                closing = chain.length - 1
            }
            if (closing === -1) {
                closingQuotesRemain = false
                endToken(position)
                position += 1
                continue
            }
            if (tokenStart === -1) {
                tokenStart = position
            }
            position = closing + 1
        } else if (character === ELEMENT_SEPARATOR || WHITESPACE.test(character)) {
            endToken(position)
            position += 1
        } else {
            if (tokenStart === -1) {
                tokenStart = position
            }
            position += 1
        }
    }
    endToken(chain.length)
    return elements
}

function startsAttributeKey(elString: string, position: number): boolean {
    while (position < elString.length && ATTRIBUTE_KEY_CHARACTER.test(elString[position])) {
        position += 1
    }
    return elString[position] === '='
}

/** The attributes start at the first colon followed by key=, so a class name may contain a colon. */
function splitTagAndAttributes(elString: string): { tag: string; attributes: string | null } {
    let colon = elString.indexOf(ATTRIBUTE_SEPARATOR)
    while (colon !== -1) {
        if (startsAttributeKey(elString, colon + 1)) {
            return { tag: elString.slice(0, colon), attributes: elString.slice(colon + 1) }
        }
        colon = elString.indexOf(ATTRIBUTE_SEPARATOR, colon + 1)
    }
    return { tag: elString, attributes: null }
}

export function parseElementAttributes(attributes: string): [string, string][] {
    const pairs: [string, string][] = []
    let start = 0
    while (true) {
        const separator = attributes.indexOf('="', start)
        if (separator === -1) {
            return pairs
        }
        const valueStart = separator + 2
        const closing = findClosingQuote(attributes, valueStart)
        if (closing === -1) {
            return pairs
        }
        pairs.push([attributes.slice(start, separator), attributes.slice(valueStart, closing)])
        start = closing + 1
    }
}

export function chainToElements(chain: string): ElementType[] {
    chain = chain.replace(/\n/g, '')

    return splitElementsChain(chain).map((elString, index) => {
        const { tag, attributes } = splitTagAndAttributes(elString)

        const element: ElementType = {
            attributes: {},
            order: index,
            tag_name: '',
        }

        if (tag) {
            const tagAndClass = tag.split('.')
            element.tag_name = tagAndClass[0]
            if (tagAndClass.length > 1) {
                element.attr_class = tagAndClass.slice(1).filter(Boolean)
            }
        }

        for (const [key, value] of attributes ? parseElementAttributes(attributes) : []) {
            if (key == 'href') {
                element.href = value
            } else if (key == 'nth-child') {
                element.nth_child = parseInt(value)
            } else if (key == 'nth-of-type') {
                element.nth_of_type = parseInt(value)
            } else if (key == 'text') {
                element.text = value
            } else if (key == 'attr_id') {
                element.attr_id = value
            } else if (key) {
                if (!element.attributes) {
                    element.attributes = {}
                }
                element.attributes[key] = value
            }
        }
        return element
    })
}
