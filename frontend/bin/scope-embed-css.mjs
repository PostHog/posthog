import postcss from 'postcss'

/**
 * Confines a stylesheet to one element so a bundle can render inside another app's page without an
 * iframe or a shadow root. The embedded web app (frontend/src/embed) needs this because its CSS is
 * written for a page of its own: it sets variables on `:root`, styles `html` and `body`, keys dark
 * mode off a `theme` attribute on `body`, and compiles Tailwind with `important: true`.
 *
 * Every selector gets the root class in front of it. A leading `:root`, `html` or `body` becomes the
 * root itself, and a leading `[theme=…]` moves onto the root, because the embed sets that attribute on
 * its root element instead of `body`. The result goes into one cascade layer so its own `@layer`
 * blocks nest under that layer instead of merging with the host page's layers of the same name.
 */

// These at-rules have to stay at the top level of the stylesheet, so they are not moved into the layer.
const TOP_LEVEL_AT_RULES = new Set(['charset', 'import', 'namespace', 'font-face', 'property'])

// Rules inside these at-rules hold keyframe or page selectors, not element selectors.
const NON_ELEMENT_AT_RULES = /^(-\w+-)?(keyframes|page)$/

const LEADING_DOCUMENT_ELEMENT = /^(?::root|html|body)(?![\w-])([^\s>+~,]*)\s*/

/**
 * @param {string} selector
 * @param {string} rootClass class name of the element the stylesheet is confined to, without the dot
 * @returns {string}
 */
export function scopeSelector(selector, rootClass) {
    const root = `.${rootClass}`
    let rest = selector.trim()

    if (rest.startsWith(root) && !/^[\w-]/.test(rest.slice(root.length))) {
        return rest
    }

    let qualifiers = ''
    let matchedDocumentElement = false
    for (let match = rest.match(LEADING_DOCUMENT_ELEMENT); match; match = rest.match(LEADING_DOCUMENT_ELEMENT)) {
        matchedDocumentElement = true
        qualifiers += match[1]
        rest = rest.slice(match[0].length)
    }
    if (matchedDocumentElement) {
        return rest ? `${root}${qualifiers} ${rest}` : `${root}${qualifiers}`
    }

    if (rest.startsWith('[theme')) {
        const attributeEnd = rest.indexOf(']') + 1
        return `${root}${rest.slice(0, attributeEnd)}${rest.slice(attributeEnd)}`
    }

    return `${root} ${rest}`
}

/**
 * @param {string} css
 * @param {{ rootClass: string, layerName: string }} options
 * @returns {string}
 */
export function scopeCss(css, { rootClass, layerName }) {
    const stylesheet = postcss.parse(css)

    stylesheet.walkRules((rule) => {
        for (let parent = rule.parent; parent && parent.type !== 'root'; parent = parent.parent) {
            if (parent.type === 'atrule' && NON_ELEMENT_AT_RULES.test(parent.name)) {
                return
            }
        }
        rule.selectors = rule.selectors.map((selector) => scopeSelector(selector, rootClass))
    })

    const layer = postcss.atRule({ name: 'layer', params: layerName })
    // Moving a node into the layer removes it from `stylesheet.nodes`, so iterate over a copy.
    for (const node of stylesheet.nodes.slice()) {
        if (node.type === 'atrule' && TOP_LEVEL_AT_RULES.has(node.name)) {
            continue
        }
        layer.append(node)
    }
    stylesheet.append(layer)

    return stylesheet.toString()
}
