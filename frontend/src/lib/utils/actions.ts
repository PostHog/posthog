import { ElementType } from '~/types'

// these plus any element with cursor:pointer will be click targets
export const CLICK_TARGETS = ['a', 'button', 'input', 'select', 'textarea']
export const EXPERIMENT_TARGETS = [
    'label',
    'h1',
    'h2',
    'h3',
    'h4',
    'h5',
    'h6',
    'span',
    'img',
    'caption',
    'code',
    'dd',
    'del',
    'details',
    'dfn',
    'footer',
    'header',
    'ol',
    'small',
    'summary',
    'table',
    'tbody',
    'td',
    'th',
    'thead',
    'tr',
    'tt',
    'u',
    'ul',
]
export const CLICK_TARGET_SELECTOR = CLICK_TARGETS.join(', ')
export const EXPERIMENT_TARGET_SELECTOR = CLICK_TARGETS.concat(EXPERIMENT_TARGETS).join(', ')

// always ignore the following
export const TAGS_TO_IGNORE = ['html', 'body', 'meta', 'head', 'script', 'link', 'style']

export const escapeRegex = (str: string): string => str.replace(/([.*+?^=!:${}()|[\]/\\])/g, '\\$1')

// React's useId() produces identifiers like ":r5:" (React <= 18) or "«r5»" (React 19) that
// component libraries bake into DOM ids and attributes (e.g. id="radix-:rr:"). A new value is
// generated per render and per deploy, so an action selector anchored to one never matches again.
const UNSTABLE_GENERATED_ID_REGEX = /:r[0-9a-z]*:|«r[0-9a-z]*»/i

export function containsUnstableGeneratedId(value: string): boolean {
    return UNSTABLE_GENERATED_ID_REGEX.test(value)
}

// raw first-present matching: for callers that locate elements by their recorded
// attributes (toolbar/elements/domElementIndex.ts), where the lookup must mirror how the
// element was originally recorded. Selector building and save-as-action anchoring use
// matchesStableDataAttribute instead.
export function matchesDataAttribute(element: ElementType, dataAttributes: string[]): string | void {
    return matchDataAttributeBy(element, dataAttributes, () => true)
}

// the first configured attribute whose value is usable long-term: unstable generated ids
// are skipped in favor of a later configured attribute with a stable value
export function matchesStableDataAttribute(element: ElementType, dataAttributes: string[]): string | void {
    return matchDataAttributeBy(element, dataAttributes, (value) => !containsUnstableGeneratedId(value))
}

function matchDataAttributeBy(
    element: ElementType,
    dataAttributes: string[],
    acceptValue: (value: string) => boolean
): string | void {
    if (!element.attributes) {
        return
    }
    for (const attribute of dataAttributes) {
        const regex = new RegExp(`^attr__${attribute.split('*').map(escapeRegex).join('.*')}$`)
        const match = Object.keys(element.attributes).find((a) => regex.test(a) && acceptValue(element.attributes[a]))
        if (match) {
            return match.replace(/^attr__/, '')
        }
    }
}

// not CSS.escape: the backend selector parser matches quoted values literally, so escaping
// anything beyond \ and " (e.g. the dots in data-attr="user.settings.save") breaks server-side matching
const escapeQuotedSelectorValue = (value: string): string => value.replace(/\\/g, '\\\\').replace(/"/g, '\\"')

export function elementToSelector(element: ElementType, dataAttributes: string[]): string {
    let selector = ''
    const attribute = matchesStableDataAttribute(element, dataAttributes)
    if (attribute) {
        const attributeValue = element.attributes[`attr__${attribute}`]
        selector += `[${attribute}="${escapeQuotedSelectorValue(attributeValue)}"]`
        return selector
    }
    if (element.attr_id && !containsUnstableGeneratedId(element.attr_id)) {
        selector += `[id="${CSS.escape(element.attr_id)}"]`
        return selector
    }
    if (element.tag_name) {
        selector += CSS.escape(element.tag_name)
    }
    if (element.attr_class) {
        selector += element.attr_class
            .filter((a) => a)
            .map((a) => `.${CSS.escape(a)}`)
            .join('')
    }
    if (element.href && element.tag_name === 'a') {
        selector += `[href="${CSS.escape(element.href)}"]`
    }
    if (element.nth_child) {
        selector += `:nth-child(${parseInt(element.nth_child as any)})`
    }
    if (element.nth_of_type) {
        selector += `:nth-of-type(${parseInt(element.nth_of_type as any)})`
    }
    return selector
}
