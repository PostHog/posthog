import { querySelectorAllDeep } from 'query-selector-shadow-dom'

import { CLICK_TARGET_SELECTOR, TAGS_TO_IGNORE, escapeRegex } from 'lib/actionUtils'
import { cssEscape } from 'lib/utils/cssEscape'

import { toolbarLogger } from '~/toolbar/core/toolbarLogger'
import { captureToolbarException } from '~/toolbar/core/toolbarPosthogJS'
import { ActionStepForm } from '~/toolbar/core/types'
import { ActionStepType } from '~/types'

import { ActionStepPropertyKey } from '../actions/ActionStep'
import { elementToQuery, getSafeText, hasCursorPointer, isParentOf } from './dom'

export function elementToActionStep(element: HTMLElement, dataAttributes: string[]): ActionStepType {
    const query = elementToQuery(element, dataAttributes)

    return {
        event: '$autocapture',
        href: element.getAttribute('href') || '',
        text: getSafeText(element) || '',
        selector: query || '',
        url: window.location.protocol + '//' + window.location.host + window.location.pathname,
        url_matching: 'exact',
    }
}

export function actionStepToActionStepFormItem(
    step: ActionStepType,
    isNew = false,
    includedPropertyKeys?: ActionStepPropertyKey[]
): ActionStepForm {
    if (!step) {
        return {}
    }

    if (typeof (step as ActionStepForm).selector_selected !== 'undefined') {
        return step as ActionStepForm
    }

    if (isNew) {
        const hasSelector = !!step.selector
        if (step.tag_name === 'a') {
            return {
                ...step,
                href_selected: true,
                selector_selected: hasSelector,
                text_selected: includedPropertyKeys?.includes('text') || false,
                url_selected: includedPropertyKeys?.includes('url') || false,
            }
        } else if (step.tag_name === 'button') {
            return {
                ...step,
                text_selected: true,
                selector_selected: hasSelector,
                href_selected: includedPropertyKeys?.includes('href') || false,
                url_selected: includedPropertyKeys?.includes('url') || false,
            }
        }
        return {
            ...step,
            selector_selected: hasSelector,
            text_selected: includedPropertyKeys?.includes('text') || false,
            url_selected: includedPropertyKeys?.includes('url') || false,
            href_selected: includedPropertyKeys?.includes('href') || false,
        }
    }

    return {
        ...step,
        url_matching: step.url_matching || 'exact',
        href_selected: typeof step.href !== 'undefined' && step.href !== null,
        text_selected: typeof step.text !== 'undefined' && step.text !== null,
        selector_selected: typeof step.selector !== 'undefined' && step.selector !== null,
        url_selected: typeof step.url !== 'undefined' && step.url !== null,
    }
}

export function stepToDatabaseFormat(step: ActionStepForm): ActionStepType {
    const { href_selected, text_selected, selector_selected, url_selected, ...rest } = step
    return {
        ...rest,
        href: href_selected ? rest.href || null : null,
        text: text_selected ? rest.text || null : null,
        selector: selector_selected ? rest.selector || null : null,
        url: url_selected ? rest.url || null : null,
    }
}

export function getElementForStep(step: ActionStepForm, allElements?: HTMLElement[]): HTMLElement | null {
    if (!step) {
        return null
    }

    let selector = ''
    if (step.selector && (step.selector_selected || typeof step.selector_selected === 'undefined')) {
        selector = step.selector
    }

    if (step.href && (step.href_selected || typeof step.href_selected === 'undefined')) {
        selector += `[href="${cssEscape(step.href)}"]`
    }

    const hasText = step.text && step.text.trim() && (step.text_selected || typeof step.text_selected === 'undefined')

    if (!selector && !hasText) {
        return null
    }

    let elements = [] as HTMLElement[]
    try {
        elements = [...(querySelectorAllDeep(selector || '*', document, allElements) as unknown as HTMLElement[])]
    } catch (e) {
        toolbarLogger.error('element_step_selector', 'Cannot use selector', { selector })
        captureToolbarException(e, 'element_step_selector', { selector })
        return null
    }

    if (hasText && step?.text) {
        const textToSearch = step.text.toString().trim()
        elements = elements.filter(
            (e) =>
                TAGS_TO_IGNORE.indexOf(e.tagName.toLowerCase()) === -1 &&
                e.innerText?.trim() === textToSearch &&
                (e.matches(CLICK_TARGET_SELECTOR) || hasCursorPointer(e))
        )
        elements = elements.filter((e) => !elements.find((e2) => isParentOf(e2, e)))
    }

    if (elements.length === 1) {
        return elements[0]
    }

    // TODO: what if multiple match?

    return null
}

export function stepMatchesHref(step: ActionStepType, href: string): boolean {
    if (!step.url_matching || !step.url) {
        return true
    }
    if (step.url_matching === 'exact') {
        return href === step.url
    }
    if (step.url_matching === 'contains') {
        return matchRuleShort(href, `%${step.url}%`)
    }
    return false
}

function matchRuleShort(str: string, rule: string): boolean {
    return new RegExp('^' + rule.split('%').map(escapeRegex).join('.*') + '$').test(str)
}
