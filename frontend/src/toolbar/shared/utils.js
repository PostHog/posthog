import Simmer from 'simmerjs'

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
    // const element = events[0].elements[0]
    if (element.tag_name) {
        selector += element.tag_name
    }
    if (element.attr_id) {
        selector += `#${element.attr_id}`
    }
    if (element.attr_class) {
        selector += element.attr_class
            .filter(a => a)
            .map(a => `.${a}`)
            .join('')
    }
    if (element.href) {
        selector += `[href="${element.href}"]`
    }
    if (element.nth_child) {
        selector += `:nth-child(${element.nth_child})`
    }
    if (element.nth_of_type) {
        selector += `:nth-of-type(${element.nth_of_type})`
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
