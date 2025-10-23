import { finder } from '@medv/finder'
import { querySelectorAllDeep } from 'query-selector-shadow-dom'
import { CSSProperties } from 'react'

import { CLICK_TARGETS, CLICK_TARGET_SELECTOR, TAGS_TO_IGNORE, escapeRegex } from 'lib/actionUtils'
import { cssEscape } from 'lib/utils/cssEscape'

import { patch } from '~/toolbar/patch'
import { ActionStepForm, ElementRect } from '~/toolbar/types'
import { ActionStepType } from '~/types'

import { ActionStepPropertyKey } from './actions/ActionStep'

export const TOOLBAR_ID = '__POSTHOG_TOOLBAR__'
export const TOOLBAR_CONTAINER_CLASS = 'toolbar-global-fade-container'
export const LOCALSTORAGE_KEY = '_postHogToolbarParams'

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

    for (const { name, value } of Array.from(element.attributes)) {
        if (!dataAttributes.includes(name)) {
            continue
        }

        const escapedSelector = `[${cssEscape(name)}="${cssEscape(value)}"]`
        const unescapedSelector = `[${name}="${value}"]`

        if (querySelectorAllDeep(escapedSelector).length == 1) {
            // if we return the _valid_ escaped CSS,
            // the action matching in PostHog might not match it
            // because it's not really CSS matching
            return unescapedSelector
        }
    }

    try {
        const foundSelector = finder(element, {
            tagName: (name) => !TAGS_TO_IGNORE.includes(name),
            seedMinLength: 5, // include several selectors e.g. prefer .project-homepage > .project-header > .project-title over .project-title
            attr: (name) => {
                // preference to data attributes if they exist
                // that aren't in the PostHog preferred list - they were returned early above
                return name.startsWith('data-')
            },
        })
        return slashDotDataAttrUnescape(foundSelector)
    } catch (error) {
        console.warn('Error while trying to find a selector for element', element, error)
        return undefined
    }
}

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

export function getToolbarRootElement(): HTMLElement | null {
    return window.document.getElementById(TOOLBAR_ID) || null
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

export function trimElement(element: HTMLElement, selector?: string): HTMLElement | null {
    const target_selector = selector || CLICK_TARGET_SELECTOR
    if (!element) {
        return null
    }
    const rootElement = getToolbarRootElement()
    if (rootElement && isParentOf(element, rootElement)) {
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
        if (loopElement.matches?.(target_selector)) {
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

export function elementIsVisible(element: HTMLElement, cache: WeakMap<HTMLElement, boolean>): boolean {
    try {
        const alreadyCached = cache.get(element)
        if (alreadyCached !== undefined) {
            return alreadyCached
        }

        if (element.checkVisibility) {
            const nativeIsVisible = element.checkVisibility({
                checkOpacity: true,
                checkVisibilityCSS: true,
            })
            cache.set(element, nativeIsVisible)
            return nativeIsVisible
        }

        const style = window.getComputedStyle(element)
        const isInvisible = style.display === 'none' || style.visibility === 'hidden' || parseFloat(style.opacity) === 0
        if (isInvisible) {
            cache.set(element, false)
            return false
        }

        // Check parent chain for display/visibility
        let parent = element.parentElement
        while (parent) {
            // Check cache first
            const cached = cache.get(parent)
            if (cached !== undefined) {
                if (!cached) {
                    return false
                }
                // If cached as visible, skip to next parent
                parent = parent.parentElement
                continue
            }

            const parentStyle = window.getComputedStyle(parent)
            const parentVisible = parentStyle.display !== 'none' && parentStyle.visibility !== 'hidden'

            cache.set(parent, parentVisible)

            if (!parentVisible) {
                return false
            }
            parent = parent.parentElement
        }

        // Check if element has actual rendered dimensions
        const rect = element.getBoundingClientRect()
        const elementHasActualRenderedDimensions =
            rect.width > 0 ||
            rect.height > 0 ||
            // Some elements might be 0x0 but still visible (e.g., inline elements with content)
            element.getClientRects().length > 0
        cache.set(element, elementHasActualRenderedDimensions)
        return elementHasActualRenderedDimensions
    } catch {
        // if we can't get the computed style, we'll assume the element is visible
        return true
    }
}

export function getAllClickTargets(
    startNode: Document | HTMLElement | ShadowRoot = document,
    selector?: string
): HTMLElement[] {
    const targetSelector = selector || CLICK_TARGET_SELECTOR
    const elements = startNode.querySelectorAll(targetSelector) as unknown as HTMLElement[]

    const allElements = [...(startNode.querySelectorAll('*') as unknown as HTMLElement[])]

    // loop through all elements and getComputedStyle
    const pointerElements = allElements.filter((el) => {
        if (CLICK_TARGETS.indexOf(el.tagName.toLowerCase()) >= 0) {
            return false
        }
        const compStyles = window.getComputedStyle(el)
        return compStyles.getPropertyValue('cursor') === 'pointer'
    })

    const shadowElements = allElements
        .filter((el) => el.shadowRoot && el.getAttribute('id') !== TOOLBAR_ID)
        .map((el: HTMLElement) => (el.shadowRoot ? getAllClickTargets(el.shadowRoot, targetSelector) : []))
        .reduce((a, b) => {
            a.push(...b)
            return a
        }, [] as HTMLElement[])
    const selectedElements = [...elements, ...pointerElements, ...shadowElements]
        .map((e) => trimElement(e, targetSelector))
        .filter((e) => e)
    const uniqueElements = Array.from(new Set(selectedElements)) as HTMLElement[]

    const visibilityCache = new WeakMap<HTMLElement, boolean>()
    return uniqueElements.filter((el) => elementIsVisible(el, visibilityCache))
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
        elements = [...(querySelectorAllDeep(selector || '*', document, allElements) as unknown as HTMLElement[])]
    } catch (e) {
        console.error('Cannot use selector:', selector, '. with exception: ', e)
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

export function getBoxColors(color: 'blue' | 'red' | 'green', hover = false, opacity = 0.2): CSSProperties | undefined {
    if (color === 'blue') {
        return {
            backgroundBlendMode: 'multiply',
            background: `hsla(240, 90%, 58%, ${opacity})`,
            boxShadow: `hsla(240, 90%, 27%, 0.2) 0px 3px 10px ${hover ? 4 : 0}px`,
            outline: `hsla(240, 90%, 58%, 0.5) solid 1px`,
        }
    }
    if (color === 'red') {
        return {
            backgroundBlendMode: 'multiply',
            background: `hsla(4, 90%, 58%, ${opacity})`,
            boxShadow: `hsla(4, 90%, 27%, 0.2) 0px 3px 10px ${hover ? 5 : 0}px`,
            outline: `hsla(4, 90%, 58%, 0.5) solid 1px`,
        }
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

export function getRectForElement(element: HTMLElement): ElementRect {
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

export const getZoomLevel = (el: HTMLElement): number[] => {
    const zooms: number[] = []
    const getZoom = (el: HTMLElement): void => {
        const zoom = window.getComputedStyle(el).getPropertyValue('zoom')
        const rzoom = zoom ? parseFloat(zoom) : 1
        if (rzoom !== 1) {
            zooms.push(rzoom)
        }
        if (el.parentElement?.parentElement) {
            getZoom(el.parentElement)
        }
    }
    getZoom(el)
    zooms.reverse()
    return zooms
}
export const getRect = (el: HTMLElement): ElementRect => {
    if (!el) {
        return { x: 0, y: 0, width: 0, height: 0, top: 0, right: 0, bottom: 0, left: 0 }
    }
    const rect = el?.getBoundingClientRect()
    const zooms = getZoomLevel(el)
    const rectWithZoom: ElementRect = {
        bottom: zooms.reduce((a, b) => a * b, rect.bottom),
        height: zooms.reduce((a, b) => a * b, rect.height),
        left: zooms.reduce((a, b) => a * b, rect.left),
        right: zooms.reduce((a, b) => a * b, rect.right),
        top: zooms.reduce((a, b) => a * b, rect.top),
        width: zooms.reduce((a, b) => a * b, rect.width),
        x: zooms.reduce((a, b) => a * b, rect.x),
        y: zooms.reduce((a, b) => a * b, rect.y),
    }
    return rectWithZoom
}

function elementToAreaRect(element: HTMLElement): { element: HTMLElement; rect: ElementRect; area: number } {
    const rect = getRect(element)
    return {
        element,
        rect,
        area: (rect.width ?? 0) * (rect.height ?? 0),
    }
}

export function getHeatMapHue(count: number, maxCount: number): number {
    if (maxCount === 0) {
        return 60
    }
    return 60 - (count / maxCount) * 40
}

/*
 * KLUDGE: e.g. [data-attr="session\.recording\.preview"] is valid CSS
 * but our action matching doesn't support it
 * in order to avoid trying to write a general purpose CSS unescaper
 * we just remove the backslash in this specific pattern
 * if it matches data-attr="bla\.blah\.blah"
 */
export function slashDotDataAttrUnescape(foundSelector: string): string | undefined {
    return foundSelector.replace(/\\./g, '.')
}

export function makeNavigateWrapper(onNavigate: () => void, patchKey: string): () => () => void {
    return () => {
        let unwrapPushState: undefined | (() => void)
        let unwrapReplaceState: undefined | (() => void)
        if (!(window.history.pushState as any)?.[patchKey]) {
            unwrapPushState = patch(
                window.history,
                'pushState',
                (originalPushState) => {
                    return function patchedPushState(
                        this: History,
                        state: any,
                        title: string,
                        url?: string | URL | null
                    ): void {
                        ;(originalPushState as History['pushState']).call(this, state, title, url)
                        onNavigate()
                    }
                },
                patchKey
            )
        }

        if (!(window.history.replaceState as any)?.[patchKey]) {
            unwrapReplaceState = patch(
                window.history,
                'replaceState',
                (originalReplaceState) => {
                    return function patchedReplaceState(
                        this: History,
                        state: any,
                        title: string,
                        url?: string | URL | null
                    ): void {
                        ;(originalReplaceState as History['replaceState']).call(this, state, title, url)
                        onNavigate()
                    }
                },
                patchKey
            )
        }

        return () => {
            unwrapPushState?.()
            unwrapReplaceState?.()
        }
    }
}
