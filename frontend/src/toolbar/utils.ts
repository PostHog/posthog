import Simmer, { Simmer as SimmerType } from '@posthog/simmerjs'
import { cssEscape } from 'lib/utils/cssEscape'
import { ActionStepType, ActionStepUrlMatching, ElementType } from '~/types'
import { ActionStepForm, BoxColor } from '~/toolbar/types'
import { querySelectorAllDeep } from 'query-selector-shadow-dom'
import { toolbarLogic } from '~/toolbar/toolbarLogic'
import { encodeParams } from 'kea-router'

// these plus any element with cursor:pointer will be click targets
const CLICK_TARGET_SELECTOR = `a, button, input, select, textarea, label`

// always ignore the following
const TAGS_TO_IGNORE = ['html', 'body', 'meta', 'head', 'script', 'link', 'style']

let simmer: SimmerType

export function getSafeText(el: HTMLElement): string {
    if (!el.childNodes || !el.childNodes.length) {
        return ''
    }
    let elText = ''
    el.childNodes.forEach((child) => {
        if (child.nodeType !== 3 || !child.textContent) {
            return
        }
        elText += child.textContent
            .trim()
            .replace(/[\r\n]/g, ' ')
            .replace(/[ ]+/g, ' ') // normalize whitespace
            .substring(0, 255)
    })
    return elText
}

export function elementToQuery(element: HTMLElement, dataAttributes: string[]): string | undefined {
    if (!element) {
        return
    }
    if (!simmer) {
        simmer = new Simmer(window, { depth: 8, dataAttributes })
    }

    // Turn tags into lower cases
    return simmer(element)?.replace(/(^[A-Z\-]+| [A-Z\-]+)/g, (d: string) => d.toLowerCase())
}

export function elementToActionStep(element: HTMLElement, dataAttributes: string[]): ActionStepType {
    const query = elementToQuery(element, dataAttributes)
    const tagName = element.tagName.toLowerCase()

    return {
        event: '$autocapture',
        tag_name: tagName,
        href: element.getAttribute('href') || '',
        name: element.getAttribute('name') || '',
        text: getSafeText(element) || '',
        selector: query || '',
        url: window.location.protocol + '//' + window.location.host + window.location.pathname,
        url_matching: ActionStepUrlMatching.Exact,
    }
}

export function elementToSelector(element: ElementType): string {
    let selector = ''
    if (element.tag_name) {
        selector += cssEscape(element.tag_name)
    }
    if (element.attributes?.['attr__data-attr']) {
        selector += `[data-attr="${element.attributes['attr__data-attr']}"]`
        return selector
    }
    if (element.attr_id) {
        selector += `#${cssEscape(element.attr_id)}`
        return selector
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

export function getToolbarElement(): HTMLElement | null {
    return window.document.getElementById('__POSTHOG_TOOLBAR__') || null
}

export function getShadowRoot(): ShadowRoot | null {
    return getToolbarElement()?.shadowRoot || null
}

export function getShadowRootPopupContainer(): HTMLElement {
    return (getShadowRoot() as unknown) as HTMLElement
}

export function hasCursorPointer(element: HTMLElement): boolean {
    return window.getComputedStyle(element)?.getPropertyValue('cursor') === 'pointer'
}

export function getParent(element: HTMLElement): HTMLElement | null {
    const parent = element.parentNode
    // 11 = DOCUMENT_FRAGMENT_NODE
    if (parent?.nodeType === window.Node.DOCUMENT_FRAGMENT_NODE) {
        return (parent as ShadowRoot).host as HTMLElement
    }
    if (parent?.nodeType === window.Node.ELEMENT_NODE) {
        return parent as HTMLElement
    }
    return null
}

export function trimElement(element: HTMLElement): HTMLElement | null {
    if (!element) {
        return null
    }
    const toolbarElement = getToolbarElement()
    if (toolbarElement && isParentOf(element, toolbarElement)) {
        return null
    }

    let loopElement = element

    // if it's an element with only one child, go down to the lowest node as far as we can
    // we'll come back up later
    while (true) {
        if (loopElement.children.length === 1) {
            loopElement = loopElement.children[0] as HTMLElement
        } else {
            break
        }
    }

    while (loopElement) {
        const parent = getParent(loopElement)
        if (!parent) {
            return null
        }

        // return when we find a click target
        if (loopElement.matches?.(CLICK_TARGET_SELECTOR)) {
            return loopElement
        }

        const compStyles = window.getComputedStyle(loopElement)
        if (compStyles.getPropertyValue('cursor') === 'pointer') {
            const parentStyles = parent ? window.getComputedStyle(parent) : null
            if (!parentStyles || parentStyles.getPropertyValue('cursor') !== 'pointer') {
                return loopElement
            }
        }

        loopElement = parent
    }

    return null
}

export function inBounds(min: number, value: number, max: number): number {
    return Math.max(min, Math.min(max, value))
}

export function getAllClickTargets(startNode: Document | HTMLElement | ShadowRoot = document): HTMLElement[] {
    const elements = (startNode.querySelectorAll(CLICK_TARGET_SELECTOR) as unknown) as HTMLElement[]

    const allElements = [...((startNode.querySelectorAll('*') as unknown) as HTMLElement[])]
    const clickTags = CLICK_TARGET_SELECTOR.split(',').map((c) => c.trim())

    // loop through all elements and getComputedStyle
    const pointerElements = allElements.filter((el) => {
        if (clickTags.indexOf(el.tagName.toLowerCase()) >= 0) {
            return false
        }
        const compStyles = window.getComputedStyle(el)
        return compStyles.getPropertyValue('cursor') === 'pointer'
    })

    const shadowElements = allElements
        .filter((el) => el.shadowRoot && el.getAttribute('id') !== '__POSTHOG_TOOLBAR__')
        .map((el: HTMLElement) => (el.shadowRoot ? getAllClickTargets(el.shadowRoot) : []))
        .reduce((a, b) => [...a, ...b], [])
    const selectedElements = [...elements, ...pointerElements, ...shadowElements]
        .map((e) => trimElement(e))
        .filter((e) => e)
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
    const escapeRegex = (strng: string): string => strng.replace(/([.*+?^=!:${}()|[\]/\\])/g, '\\$1')
    return new RegExp('^' + rule.split('%').map(escapeRegex).join('.*') + '$').test(str)
}

export function isParentOf(element: HTMLElement, possibleParent: HTMLElement): boolean {
    let loopElement = element as HTMLElement | null
    while (loopElement) {
        if (loopElement !== element && loopElement === possibleParent) {
            return true
        }
        loopElement = getParent(loopElement)
    }

    return false
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
        elements = [...((querySelectorAllDeep(selector || '*', document, allElements) as unknown) as HTMLElement[])]
    } catch (e) {
        console.error('Can not use selector:', selector)
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
        const hasSelector = !!step.selector
        if (step.tag_name === 'a') {
            return {
                ...step,
                href_selected: true,
                selector_selected: hasSelector,
                text_selected: false,
                url_selected: false,
            }
        } else if (step.tag_name === 'button') {
            return {
                ...step,
                text_selected: true,
                selector_selected: hasSelector,
                href_selected: false,
                url_selected: false,
            }
        } else {
            return {
                ...step,
                selector_selected: hasSelector,
                text_selected: false,
                url_selected: false,
                href_selected: false,
            }
        }
    }

    const newStep = {
        ...step,
        url_matching: step.url_matching || ActionStepUrlMatching.Exact,
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

export function getRectForElement(element: HTMLElement): DOMRect {
    const elements = [elementToAreaRect(element)]

    let loopElement = element
    while (loopElement.children.length === 1) {
        loopElement = loopElement.children[0] as HTMLElement
        elements.push(elementToAreaRect(loopElement))
    }

    let maxArea = 0
    let maxRect = elements[0].rect

    for (const { rect, area } of elements) {
        if (area >= maxArea) {
            maxArea = area
            maxRect = rect
        }
    }

    return maxRect
}

function elementToAreaRect(element: HTMLElement): { element: HTMLElement; rect: DOMRect; area: number } {
    const rect = element.getBoundingClientRect()
    return {
        element,
        rect,
        area: rect.width * rect.height,
    }
}

export function getHeatMapHue(count: number, maxCount: number): number {
    if (maxCount === 0) {
        return 60
    }
    return 60 - (count / maxCount) * 40
}

export async function toolbarFetch(
    url: string,
    method: string = 'GET',
    payload?: Record<string, any>
): Promise<Response> {
    const params = {
        temporary_token: toolbarLogic.values.temporaryToken,
    }
    const fullUrl = `${toolbarLogic.values.apiURL}${url.startsWith('/') ? url.substring(1) : url}${encodeParams(
        params,
        '?'
    )}`

    const payloadData = payload
        ? {
              body: JSON.stringify(payload),
              headers: {
                  'Content-Type': 'application/json',
              },
          }
        : {}

    const response = await fetch(fullUrl, {
        method,
        ...payloadData,
    })
    if (response.status === 403) {
        toolbarLogic.actions.authenticate()
    }
    return response
}
