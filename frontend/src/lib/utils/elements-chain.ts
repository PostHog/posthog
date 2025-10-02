import { ElementType } from '~/types'

// NOTE: This function should not be edited directly but rather copied from plugin-server/src/utils/db/elements-chain.ts
export function chainToElements(chain: string, options: { throwOnError?: boolean } = {}): ElementType[] {
    const elements: ElementType[] = []

    // Below splits all elements by ;, while ignoring escaped quotes and semicolons within quotes
    const splitChainRegex = /(?:[^\s;"]|"(?:\\.|[^"])*")+/g

    // Below splits the tag/classes from attributes
    // Needs a regex because classes can have : too
    const splitClassAttributes = /(.*?)($|:([a-zA-Z\-_0-9]*=.*))/g
    const parseAttributesRegex = /((.*?)="((?:\\"|[^"])*)")/gm

    chain = chain.replace(/\n/g, '')

    try {
        Array.from(chain.matchAll(splitChainRegex))
            .map((r) => r[0])
            .forEach((elString, index) => {
                const elStringSplit = Array.from(elString.matchAll(splitClassAttributes))[0]
                const attributes =
                    elStringSplit.length > 3 && elStringSplit[3]
                        ? Array.from(elStringSplit[3].matchAll(parseAttributesRegex)).map((a) => [a[2], a[3]])
                        : []

                const element: ElementType = {
                    attributes: {},
                    order: index,
                    tag_name: '',
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
        if (options.throwOnError) {
            throw error
        }
    }
    return elements
}
