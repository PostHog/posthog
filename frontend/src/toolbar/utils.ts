import Simmer from '@mariusandra/simmerjs'
import { cssEscape } from 'lib/utils/cssEscape'
import { ActionStepType, ElementType } from '~/types'
import { ActionStepForm, BoxColor } from '~/toolbar/types'

const CLICK_TARGET_SELECTOR = `a, button, input, select, textarea, label`

// This trims the "hovered" DOM node down. For example:
// - div > div > div > svg > path  <--- ignore the path, just inpsect the full image/svg
// - div > div > button > span     <--- we probably care about the button, not the span
// - div > div > a > span          <--- same with links
const DOM_TRIM_DOWN_SELECTOR = 'a, svg, button'
const TAGS_TO_IGNORE = ['html', 'body', 'meta', 'head', 'script', 'link', 'style']

const simmer = new Simmer(window, { depth: 8 })

export function getSafeText(el: HTMLElement): string {
    if (!el.childNodes || !el.childNodes.length) return ''
    let elText = ''
    el.childNodes.forEach((child) => {
        if (child.nodeType !== 3 || !child.textContent) return
        elText += child.textContent
            .trim()
            .replace(/[\r\n]/g, ' ')
            .replace(/[ ]+/g, ' ') // normalize whitespace
            .substring(0, 255)
    })
    return elText
}

export function elementToQuery(element: HTMLElement): string | null {
    if (!element) {
        return null
    }
    return (
        simmer(element)
            // Turn tags into lower cases
            .replace(/(^[A-Z]+| [A-Z]+)/g, (d: string) => d.toLowerCase())
    )
}

export function elementToActionStep(element: HTMLElement): ActionStepType {
    const query = elementToQuery(element)
    const tagName = element.tagName.toLowerCase()

    return {
        event: '$autocapture',
        tag_name: tagName,
        href: element.getAttribute('href') || '',
        name: element.getAttribute('name') || '',
        text: getSafeText(element) || '',
        selector: query || '',
        url: window.location.protocol + '//' + window.location.host + window.location.pathname,
        url_matching: 'exact',
    }
}

export function elementToSelector(element: ElementType): string {
    let selector = ''
    if (element.tag_name) {
        selector += cssEscape(element.tag_name)
    }
    if (element.attr_id) {
        selector += `#${cssEscape(element.attr_id)}`
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

export function getShadowRoot(): ShadowRoot | null {
    return window.document.getElementById('__POSTHOG_TOOLBAR__')?.shadowRoot || null
}

export function getShadowRootPopupContainer(): HTMLElement {
    return (getShadowRoot() as unknown) as HTMLElement
}

export function hasCursorPointer(element: HTMLElement): boolean {
    return window.getComputedStyle(element)?.getPropertyValue('cursor') === 'pointer'
}

export function trimElement(element: HTMLElement, selectingClickTargets = false): HTMLElement | null {
    if (!element) {
        return null
    }
    if (element && element.getAttribute('id') === '__POSTHOG_TOOLBAR__') {
        return null
    }

    let loopElement = element
    if (selectingClickTargets) {
        while (loopElement?.parentElement) {
            // return when we find a click target
            if (loopElement.matches(CLICK_TARGET_SELECTOR)) {
                return loopElement
            }
            const compStyles = window.getComputedStyle(loopElement)
            if (compStyles.getPropertyValue('cursor') === 'pointer') {
                const parentStyles = loopElement.parentElement
                    ? window.getComputedStyle(loopElement.parentElement)
                    : null
                if (!parentStyles || parentStyles.getPropertyValue('cursor') !== 'pointer') {
                    return loopElement
                }
            }

            loopElement = loopElement.parentElement
        }
        return null
    } else {
        // selecting all elements
        let selectedElement = loopElement
        while (loopElement?.parentElement) {
            // trim down the dom nodes
            if (loopElement.matches(DOM_TRIM_DOWN_SELECTOR)) {
                selectedElement = loopElement
            }
            loopElement = loopElement.parentElement
        }
        return selectedElement
    }
}

export function inBounds(min: number, value: number, max: number): number {
    return Math.max(min, Math.min(max, value))
}

export function getAllClickTargets(): HTMLElement[] {
    const elements = (document.querySelectorAll(CLICK_TARGET_SELECTOR) as unknown) as HTMLElement[]

    const allElements = [...((document.querySelectorAll('*') as unknown) as HTMLElement[])]
    const clickTags = CLICK_TARGET_SELECTOR.split(',').map((c) => c.trim())

    // loop through all elements and getComputedStyle
    const pointerElements = allElements.filter((el) => {
        if (clickTags.indexOf(el.tagName.toLowerCase()) >= 0) {
            return false
        }
        const compStyles = window.getComputedStyle(el)
        return compStyles.getPropertyValue('cursor') === 'pointer'
    })

    const selectedElements = [...elements, ...pointerElements].map((e) => trimElement(e, true))
    const uniqueElements = Array.from(new Set(selectedElements)) as HTMLElement[]

    return uniqueElements
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
    const escapeRegex = (str: string): string => str.replace(/([.*+?^=!:${}()|[\]/\\])/g, '\\$1')
    return new RegExp('^' + rule.split('%').map(escapeRegex).join('.*') + '$').test(str)
}

export function isParentOf(element: HTMLElement, possibleParent: HTMLElement): boolean {
    let loopElement = element as HTMLElement | null
    while (loopElement) {
        if (loopElement !== element && loopElement === possibleParent) {
            return true
        }
        loopElement = loopElement.parentElement
    }

    return false
}

export function getElementForStep(step: ActionStepForm): HTMLElement | null {
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
        elements = [...((document.querySelectorAll(selector || '*') as unknown) as HTMLElement[])]
    } catch (e) {
        console.error('Can not use selector:', selector)
        throw e
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

export function getBoxColors(color: 'blue' | 'red' | 'green', hover = false, opacity = 0.2): BoxColor | undefined {
    if (color === 'blue') {
        return {
            backgroundBlendMode: 'multiply',
            background: `hsla(240, 90%, 58%, ${opacity})`,
            boxShadow: `hsla(240, 90%, 27%, 0.5) 0px 3px 10px ${hover ? 4 : 2}px`,
        }
    }
    if (color === 'red') {
        return {
            backgroundBlendMode: 'multiply',
            background: `hsla(4, 90%, 58%, ${opacity})`,
            boxShadow: `hsla(4, 90%, 27%, 0.8) 0px 3px 10px ${hover ? 4 : 2}px`,
        }
    }
    if (color === 'green') {
        return {
            backgroundBlendMode: 'multiply',
            background: `hsla(97, 90%, 58%, ${opacity})`,
            boxShadow: `hsla(97, 90%, 27%, 0.8) 0px 3px 10px ${hover ? 4 : 2}px`,
        }
    }
}

export function actionStepToAntdForm(step: ActionStepType, isNew = false): ActionStepForm {
    if (!step) {
        return {}
    }

    if (typeof (step as ActionStepForm).selector_selected !== 'undefined') {
        return step as ActionStepForm
    }

    if (isNew) {
        if (step.tag_name === 'a') {
            return { ...step, href_selected: true, selector_selected: true, text_selected: false, url_selected: false }
        } else if (step.tag_name === 'button') {
            return { ...step, text_selected: true, selector_selected: true, href_selected: false, url_selected: false }
        } else {
            return { ...step, selector_selected: true, text_selected: false, url_selected: false, href_selected: false }
        }
    }

    const newStep = {
        ...step,
        url_matching: step.url_matching || 'exact',
        href_selected: typeof step.href !== 'undefined' && step.href !== null,
        text_selected: typeof step.text !== 'undefined' && step.text !== null,
        selector_selected: typeof step.selector !== 'undefined' && step.selector !== null,
        url_selected: typeof step.url !== 'undefined' && step.url !== null,
    }
    return newStep
}

export function stepToDatabaseFormat(step: ActionStepForm): ActionStepType {
    const { href_selected, text_selected, selector_selected, url_selected, ...rest } = step
    const newStep = {
        ...rest,
        href: href_selected ? rest.href : undefined,
        text: text_selected ? rest.text : undefined,
        selector: selector_selected ? rest.selector : undefined,
        url: url_selected ? rest.url : undefined,
    }
    return newStep
}

export function clearSessionToolbarToken(): void {
    window.sessionStorage?.removeItem('_postHogEditorParams')
    window.localStorage?.removeItem('_postHogEditorParams')
}
