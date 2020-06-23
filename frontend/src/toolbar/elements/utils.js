import Simmer from 'simmerjs'
import { cssEscape } from 'lib/utils/cssEscape'

const simmer = new Simmer(window, { depth: 8 })

export function getSafeText(el) {
    if (!el.childNodes || !el.childNodes.length) return
    let elText = ''
    el.childNodes.forEach(child => {
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
            .replace(/(^[A-Z]+| [A-Z]+)/g, d => d.toLowerCase())
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
            .filter(a => a)
            .map(a => `.${cssEscape(a)}`)
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

const CLICK_TARGET_SELECTOR = `a, button, input, select, textarea, label`

// This trims the "hovered" DOM node down. For example:
// - div > div > div > svg > path  <--- ignore the path, just inpsect the full image/svg
// - div > div > button > span     <--- we probably care about the button, not the span
// - div > div > a > span          <--- same with links
const DOM_TRIM_DOWN_SELECTOR = 'a, svg, button'

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
    const clickTags = CLICK_TARGET_SELECTOR.split(',').map(c => c.trim())

    // loop through all elements and getComputedStyle
    const pointerElements = allElements.filter(el => {
        if (clickTags.indexOf(el.tagName.toLowerCase()) >= 0) {
            return false
        }
        let compStyles = window.getComputedStyle(el)
        return compStyles.getPropertyValue('cursor') === 'pointer'
    })

    const selectedElements = [...elements, ...pointerElements].map(e => trimElement(e, true))
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
    const escapeRegex = str => str.replace(/([.*+?^=!:${}()|[\]/\\])/g, '\\$1')
    return new RegExp(
        '^' +
            rule
                .split('%')
                .map(escapeRegex)
                .join('.*') +
            '$'
    ).test(str)
}

export function getElementForStep(step) {
    let selector = ''
    if (step.selector) {
        selector = step.selector
    }
    if (step.href) {
        selector += `[href="${cssEscape(step.href)}"]`
    }
    if (step.text) {
        // TODO
        // selector += `:nth-of-type(${parseInt(element.nth_of_type)})`
    }

    if (!selector) {
        return null
    }

    try {
        const elements = document.querySelectorAll(selector)
        if (elements.length === 1) {
            return elements[0]
        }
        // TODO: what if multiple match?
    } catch (e) {
        console.error('Can not use selector:', selector)
        throw e
    }
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

export function actionStepToAntdForm(step) {
    if (!step) {
        return undefined
    }
    const newStep = {
        ...step,
        url_matching: step.url_matching || 'exact',
        href_selected: step.href !== null,
        text_selected: step.text !== null,
        selector_selected: step.selector !== null,
        url_selected: step.url !== null,
    }
    return newStep
}
