import { Matcher, MatcherOptions, queryHelpers } from '@testing-library/dom'

export const queryByDataAttr = queryHelpers.queryByAttribute.bind(null, 'data-attr')
export const queryAllByDataAttr = queryHelpers.queryAllByAttribute.bind(null, 'data-attr')

export function getAllByDataAttr(container: HTMLElement, id: Matcher, options?: MatcherOptions): HTMLElement[] {
    const els = queryAllByDataAttr(container, id, options)
    if (!els.length) {
        throw queryHelpers.getElementError(`Unable to find an element by: [data-attr="${id}"]`, container)
    }
    return els
}

export function getByDataAttr(container: HTMLElement, id: Matcher, options?: MatcherOptions): HTMLElement {
    const result = getAllByDataAttr(container, id, options)
    if (result.length > 1) {
        throw queryHelpers.getElementError(`Found multiple elements with [data-attr="${id}"]`, container)
    }
    if (!result.length) {
        throw queryHelpers.getElementError(`Did not find an element with [data-attr="${id}"]`, container)
    }
    return result[0]
}

// re-export with overrides
module.exports = {
    getByDataAttr,
    getAllByDataAttr,
    queryByDataAttr,
    queryAllByDataAttr,
}
