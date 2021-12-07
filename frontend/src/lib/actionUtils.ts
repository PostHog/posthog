import { ElementType } from '~/types'
import { cssEscape } from 'lib/utils/cssEscape'

// these plus any element with cursor:pointer will be click targets
export const CLICK_TARGETS = ['a', 'button', 'input', 'select', 'textarea', 'label']
export const CLICK_TARGET_SELECTOR = CLICK_TARGETS.join(', ')

// always ignore the following
export const TAGS_TO_IGNORE = ['html', 'body', 'meta', 'head', 'script', 'link', 'style']

export const escapeRegex = (str: string): string => str.replace(/([.*+?^=!:${}()|\[\]\/\\])/g, '\\$1')

export function matchesDataAttribute(element: ElementType, dataAttributes: string[]): string | void {
    if (!element.attributes) {
        return
    }
    for (const attribute of dataAttributes) {
        const regex = new RegExp(`^attr__${attribute.split('*').map(escapeRegex).join('.*')}$`)
        const match = Object.keys(element.attributes).find((a) => regex.test(a))
        if (match) {
            return match.replace(/^attr__/, '')
        }
    }
}

export function elementToSelector(element: ElementType, dataAttributes: string[]): string {
    let selector = ''
    const attribute = matchesDataAttribute(element, dataAttributes)
    if (attribute) {
        selector += `[${attribute}="${element.attributes[`attr__${attribute}`]}"]`
        return selector
    }
    if (element.attr_id) {
        selector += `#${cssEscape(element.attr_id)}`
        return selector
    }
    if (element.tag_name) {
        selector += cssEscape(element.tag_name)
    }
    if (element.attr_class) {
        selector += element.attr_class
            .filter((a) => a)
            .map((a) => `.${cssEscape(a)}`)
            .join('')
    }
    if (element.href && element.tag_name === 'a') {
        selector += `[href="${cssEscape(element.href)}"]`
    }
    if (element.nth_child) {
        selector += `:nth-child(${parseInt(element.nth_child as any)})`
    }
    if (element.nth_of_type) {
        selector += `:nth-of-type(${parseInt(element.nth_of_type as any)})`
    }
    return selector
}
