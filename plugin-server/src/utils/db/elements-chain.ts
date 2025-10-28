import { Element } from '../../types'
import { captureException } from '../posthog'
import { createTrackedRE2 } from '../tracked-re2'
import { escapeQuotes } from './utils'

// Below splits all elements by ;, while ignoring escaped quotes and semicolons within quotes
const splitChainRegex = createTrackedRE2(/(?:[^\s;"]|"(?:[^"\\]|\\.)*")+/g, undefined, 'elements-chain:split')
// Below splits the tag/classes from attributes
// Needs a regex because classes can have : too
const splitClassAttributes = createTrackedRE2(/(.*?)($|:([a-zA-Z\-_0-9]*=.*))/g, undefined, 'elements-chain:splitClass')
const parseAttributesRegex = createTrackedRE2(/((.*?)="(.*?[^\\])")/gm, undefined, 'elements-chain:parseAttributes')
const newLine = createTrackedRE2(/\\n/g, undefined, 'elements-chain:newLine')

export function elementsToString(elements: Element[]): string {
    const ret = elements.map((element) => {
        let el_string = ''
        if (element.tag_name) {
            el_string += element.tag_name
        }
        if (element.attr_class) {
            element.attr_class.sort()
            for (const single_class of element.attr_class) {
                el_string += `.${single_class.replace(/"/g, '')}`
            }
        }
        let attributes: Record<string, any> = {
            ...(element.text ? { text: element.text } : {}),
            'nth-child': element.nth_child ?? 0,
            'nth-of-type': element.nth_of_type ?? 0,
            ...(element.href ? { href: element.href } : {}),
            ...(element.attr_id ? { attr_id: element.attr_id } : {}),
            ...element.attributes,
        }
        attributes = Object.fromEntries(
            Object.entries(attributes)
                .sort(([a], [b]) => a.localeCompare(b))
                .map(([key, value]) => [escapeQuotes(key.toString()), escapeQuotes(value.toString())])
        )
        el_string += ':'
        el_string += Object.entries(attributes)
            .map(([key, value]) => `${key}="${value}"`)
            .join('')
        return el_string
    })
    return ret.join(';')
}

export function chainToElements(chain: string, teamId: number, options: { throwOnError?: boolean } = {}): Element[] {
    const elements: Element[] = []

    chain = chain.replaceAll(newLine, '')

    try {
        Array.from(chain.matchAll(splitChainRegex))
            .map((r) => r[0])
            .forEach((elString, index) => {
                const elStringSplit = Array.from(elString.matchAll(splitClassAttributes))[0]
                const attributes =
                    elStringSplit.length > 3 && elStringSplit[3]
                        ? Array.from(elStringSplit[3].matchAll(parseAttributesRegex)).map((a) => [a[2], a[3]])
                        : []

                const element: Element = {
                    attributes: {},
                    order: index,
                }

                if (elStringSplit[1]) {
                    const tagAndClass = elStringSplit[1].split('.')
                    element.tag_name = tagAndClass[0]
                    if (tagAndClass.length > 1) {
                        element.attr_class = tagAndClass.slice(1).filter(Boolean)
                    }
                }

                for (const [key, value] of attributes) {
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
                elements.push(element)
            })
    } catch (error) {
        captureException(error, { tags: { team_id: teamId }, extra: { chain } })
        if (options.throwOnError) {
            throw error
        }
    }
    return elements
}

export function extractElements(elements: Array<Record<string, any>>): Element[] {
    return elements.map((el) => ({
        text: el['$el_text']?.slice(0, 400),
        tag_name: el['tag_name'],
        href: el['attr__href']?.slice(0, 2048),
        attr_class: extractAttrClass(el),
        attr_id: el['attr__id'],
        nth_child: el['nth_child'],
        nth_of_type: el['nth_of_type'],
        attributes: Object.fromEntries(Object.entries(el).filter(([key]) => key.startsWith('attr__'))),
    }))
}

function extractAttrClass(el: Record<string, any>): Element['attr_class'] {
    const attr_class = el['attr__class']
    if (!attr_class) {
        return undefined
    } else if (Array.isArray(attr_class)) {
        return attr_class
    } else {
        return attr_class.split(' ')
    }
}
