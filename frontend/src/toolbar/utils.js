import Simmer from 'simmerjs'
import { cssEscape } from 'lib/utils/cssEscape'

const CLICK_TARGET_SELECTOR = `a, button, input, select, textarea, label`

// This trims the "hovered" DOM node down. For example:
// - div > div > div > svg > path  <--- ignore the path, just inpsect the full image/svg
// - div > div > button > span     <--- we probably care about the button, not the span
// - div > div > a > span          <--- same with links
const DOM_TRIM_DOWN_SELECTOR = 'a, svg, button'
const TAGS_TO_IGNORE = ['html', 'body', 'meta', 'head', 'script', 'link', 'style']

const simmer = new Simmer(window, { depth: 8 })

export function getSafeText(el) {
    if (!el.childNodes || !el.childNodes.length) return
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

export function elementToQuery(element) {
    if (!element) {
        return null
    }
    return (
        simmer(element)
            // Turn tags into lower cases
            .replace(/(^[A-Z]+| [A-Z]+)/g, (d) => d.toLowerCase())
    )
}

export function elementToActionStep(element) {
    let query = elementToQuery(element)
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

export function elementToSelector(element) {
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
    if (element.href) {
        selector += `[href="${cssEscape(element.href)}"]`
    }
    if (element.nth_child) {
        selector += `:nth-child(${parseInt(element.nth_child)})`
    }
    if (element.nth_of_type) {
        selector += `:nth-of-type(${parseInt(element.nth_of_type)})`
    }
    return selector
}

export function getShadowRoot() {
    return window.document.getElementById('__POSTHOG_TOOLBAR__')?.shadowRoot
}

export function hasCursorPointer(element) {
    return window.getComputedStyle(element)?.getPropertyValue('cursor') === 'pointer'
}

export function trimElement(element, selectingClickTargets = false) {
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
            let compStyles = window.getComputedStyle(loopElement)
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

export function inBounds(min, value, max) {
    return Math.max(min, Math.min(max, value))
}

export function getAllClickTargets() {
    const elements = document.querySelectorAll(CLICK_TARGET_SELECTOR)

    let allElements = [...document.querySelectorAll('*')]
    const clickTags = CLICK_TARGET_SELECTOR.split(',').map((c) => c.trim())

    // loop through all elements and getComputedStyle
    const pointerElements = allElements.filter((el) => {
        if (clickTags.indexOf(el.tagName.toLowerCase()) >= 0) {
            return false
        }
        let compStyles = window.getComputedStyle(el)
        return compStyles.getPropertyValue('cursor') === 'pointer'
    })

    const selectedElements = [...elements, ...pointerElements].map((e) => trimElement(e, true))
    const uniqueElements = Array.from(new Set(selectedElements))

    return uniqueElements
}

export function stepMatchesHref(step, href) {
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

function matchRuleShort(str, rule) {
    const escapeRegex = (str) => str.replace(/([.*+?^=!:${}()|[\]/\\])/g, '\\$1')
    return new RegExp('^' + rule.split('%').map(escapeRegex).join('.*') + '$').test(str)
}

export function isParentOf(element, possibleParent) {
    let loopElement = element
    while (loopElement) {
        if (loopElement !== element && loopElement === possibleParent) {
            return true
        }
        loopElement = loopElement.parentElement
    }

    return false
}

export function getElementForStep(step) {
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

    let elements
    try {
        elements = document.querySelectorAll(selector || '*')
    } catch (e) {
        console.error('Can not use selector:', selector)
        throw e
    }

    if (hasText) {
        const textToSearch = step.text.toString().trim()
        elements = [...elements].filter(
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

export function getBoxColors(color, hover = false, opacity = 0.2) {
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

export function actionStepToAntdForm(step, isNew = false) {
    if (!step) {
        return {}
    }

    if (typeof step.selector_selected !== 'undefined') {
        return step
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

export function stepToDatabaseFormat(step) {
    const { href_selected, text_selected, selector_selected, url_selected, ...rest } = step
    const newStep = {
        ...rest,
        href: href_selected ? rest.href : null,
        text: text_selected ? rest.text : null,
        selector: selector_selected ? rest.selector : null,
        url: url_selected ? rest.url : null,
    }
    return newStep
}
