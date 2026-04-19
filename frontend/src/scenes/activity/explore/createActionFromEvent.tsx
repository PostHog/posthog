import { CLICK_TARGETS, elementToSelector, matchesDataAttribute } from 'lib/actionUtils'

import { ActionStepType, ElementType, PropertyFilterType, PropertyOperator } from '~/types'

export function recurseSelector(elements: ElementType[], parts: string, index: number): string {
    const element = elements[index]
    if (element.attr_id) {
        return `[id="${element.attr_id}"] > ${parts}`
    }
    if (index > 0) {
        parts = element.tag_name + ' > ' + parts
    } else {
        parts = element.tag_name
    }
    if (index === 10 || !elements[index + 1]) {
        return parts
    }
    return recurseSelector(elements, parts, index + 1)
}

export function elementsToAction(
    elements: ElementType[]
): Pick<ActionStepType, 'selector' | 'text' | 'href' | 'tag_name'> {
    return {
        href: elements[0].href,
        text: elements[0].text,
        ...(!elements[0].href && !elements[0].text ? { selector: recurseSelector(elements, '', 0) } : ''),
    }
}

export function applyDataAttributeSelector(
    step: ActionStepType,
    elements: ElementType[],
    dataAttributes: string[]
): void {
    if (dataAttributes.length === 0 || elements.length === 0) {
        return
    }
    for (let i = 0; i < elements.length; i++) {
        const element = elements[i]
        if (matchesDataAttribute(element, dataAttributes) || element.attr_id) {
            let selector = elementToSelector(element, dataAttributes)
            if (i > 0 && !CLICK_TARGETS.includes(element.tag_name)) {
                const clickedTagName = elements[0].tag_name
                selector = `${selector} > ${clickedTagName || '*'}`
            }
            step.selector = selector
            break
        }
    }
}

export function applySubmitProperty(step: ActionStepType, eventProperties: Record<string, any>): void {
    if (eventProperties.$event_type === 'submit') {
        step.properties = [
            { key: '$event_type', value: 'submit', type: PropertyFilterType.Event, operator: PropertyOperator.Exact },
        ]
    }
}
