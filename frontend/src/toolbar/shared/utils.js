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
