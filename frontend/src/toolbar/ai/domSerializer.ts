import { TOOLBAR_ID } from '~/toolbar/utils'

export interface DOMSnapshot {
    url: string
    title: string
    viewport: { width: number; height: number }
    tree: string
}

export interface DOMSerializerOptions {
    /** Maximum nesting depth to descend into. */
    maxDepth?: number
    /** Maximum number of nodes to include before bailing out. */
    maxNodes?: number
    /** Maximum length of text content per element. */
    maxTextLength?: number
    /** Optional document override (for tests). */
    document?: Document
    /** Optional window override (for tests). */
    window?: Window
}

const DEFAULT_OPTIONS: Required<Omit<DOMSerializerOptions, 'document' | 'window'>> = {
    maxDepth: 15,
    maxNodes: 2000,
    maxTextLength: 100,
}

/** `<svg>` is rendered as a self-closing leaf so the tree stays compact. */
const SKIP_CHILDREN_TAGS = new Set(['SVG'])

/** Tag names that are entirely skipped (not rendered, not descended). */
const SKIP_ENTIRELY_TAGS = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT'])

function isHidden(el: Element, win: Window): boolean {
    if (el.getAttribute('aria-hidden') === 'true') {
        return true
    }
    // getComputedStyle can throw in detached / SSR-like environments. Be defensive.
    let style: CSSStyleDeclaration | null = null
    try {
        style = win.getComputedStyle(el)
    } catch {
        return false
    }
    if (!style) {
        return false
    }
    if (style.display === 'none' || style.visibility === 'hidden') {
        return true
    }
    return false
}

function getKeyClasses(el: Element, max = 3): string[] {
    if (!el.classList || el.classList.length === 0) {
        return []
    }
    const classes: string[] = []
    for (let i = 0; i < el.classList.length && classes.length < max; i++) {
        const cls = el.classList[i]
        // Filter out auto-generated / hash-like classes (e.g. CSS modules: foo__abc123).
        if (cls && !/^(?:css-|sc-|jsx-|MuiBox-|emotion-)/.test(cls)) {
            classes.push(cls)
        }
    }
    return classes
}

function escapeAttr(value: string): string {
    // Strip quotes/newlines so the produced text remains predictable for the LLM.
    return value
        .replace(/[\r\n]+/g, ' ')
        .replace(/"/g, "'")
        .trim()
}

function getDataPhAttributes(el: Element): string[] {
    const out: string[] = []
    for (const attr of Array.from(el.attributes)) {
        if (attr.name.startsWith('data-ph-') || attr.name.startsWith('data-attr')) {
            out.push(`${attr.name}="${escapeAttr(attr.value)}"`)
        }
    }
    return out
}

function truncate(text: string, max: number): string {
    if (text.length <= max) {
        return text
    }
    return text.slice(0, max) + '...'
}

function getDirectText(el: Element, max: number): string {
    let text = ''
    for (const node of Array.from(el.childNodes)) {
        if (node.nodeType === 3 /* TEXT_NODE */) {
            text += node.nodeValue ?? ''
            if (text.length > max * 2) {
                break
            }
        }
    }
    text = text.replace(/\s+/g, ' ').trim()
    if (!text) {
        return ''
    }
    return truncate(text, max)
}

function describeOpenTag(el: Element, options: Required<Pick<DOMSerializerOptions, 'maxTextLength'>>): string {
    const tag = el.tagName.toLowerCase()
    const parts: string[] = [tag]

    if (el.id) {
        parts.push(`#${el.id}`)
    }
    const classes = getKeyClasses(el)
    for (const cls of classes) {
        parts.push(`.${cls}`)
    }
    const role = el.getAttribute('role')
    if (role) {
        parts.push(`role="${escapeAttr(role)}"`)
    }
    const ariaLabel = el.getAttribute('aria-label')
    if (ariaLabel) {
        parts.push(`aria-label="${escapeAttr(truncate(ariaLabel, options.maxTextLength))}"`)
    }
    // For links/buttons, the href / type can be informative.
    if (tag === 'a') {
        const href = el.getAttribute('href')
        if (href) {
            parts.push(`href="${escapeAttr(truncate(href, options.maxTextLength))}"`)
        }
    }
    if (tag === 'input' || tag === 'button') {
        const inputType = el.getAttribute('type')
        if (inputType) {
            parts.push(`type="${escapeAttr(inputType)}"`)
        }
        const name = el.getAttribute('name')
        if (name) {
            parts.push(`name="${escapeAttr(name)}"`)
        }
        if (tag === 'input') {
            const placeholder = el.getAttribute('placeholder')
            if (placeholder) {
                parts.push(`placeholder="${escapeAttr(truncate(placeholder, options.maxTextLength))}"`)
            }
        }
    }
    parts.push(...getDataPhAttributes(el))

    return `<${parts.join(' ')}>`
}

function indent(level: number): string {
    return '  '.repeat(level)
}

interface SerializeState {
    nodeCount: number
    truncated: boolean
}

function serializeElement(
    el: Element,
    depth: number,
    state: SerializeState,
    options: Required<Omit<DOMSerializerOptions, 'document' | 'window'>>,
    win: Window
): string[] {
    if (state.nodeCount >= options.maxNodes) {
        if (!state.truncated) {
            state.truncated = true
            return [`${indent(depth)}<!-- truncated -->`]
        }
        return []
    }

    const tagName = el.tagName.toUpperCase()
    if (SKIP_ENTIRELY_TAGS.has(tagName)) {
        return []
    }
    // Skip the toolbar entirely — it's our own UI, not part of the user's page.
    if (el.id === TOOLBAR_ID) {
        return []
    }
    if (isHidden(el, win)) {
        return []
    }

    state.nodeCount += 1

    const openTag = describeOpenTag(el, { maxTextLength: options.maxTextLength })

    // SVG: render as a leaf — its internals are noisy and rarely useful.
    if (SKIP_CHILDREN_TAGS.has(tagName) && tagName === 'SVG') {
        return [`${indent(depth)}${openTag.replace(/>$/, ' />')}`]
    }

    const children: string[] = []
    if (depth >= options.maxDepth) {
        children.push(`${indent(depth + 1)}<!-- truncated -->`)
    } else {
        // Direct text content (e.g. for buttons / links / headings)
        const directText = getDirectText(el, options.maxTextLength)
        if (directText) {
            children.push(`${indent(depth + 1)}${directText}`)
        }
        for (const child of Array.from(el.children)) {
            const rendered = serializeElement(child, depth + 1, state, options, win)
            children.push(...rendered)
            if (state.truncated) {
                break
            }
        }
    }

    const closeTag = `</${el.tagName.toLowerCase()}>`
    if (children.length === 0) {
        return [`${indent(depth)}${openTag}${closeTag}`]
    }
    return [`${indent(depth)}${openTag}`, ...children, `${indent(depth)}${closeTag}`]
}

export function serializeDOM(options: DOMSerializerOptions = {}): DOMSnapshot {
    const doc = options.document ?? document
    const win = options.window ?? doc.defaultView ?? window
    const opts: Required<Omit<DOMSerializerOptions, 'document' | 'window'>> = {
        maxDepth: options.maxDepth ?? DEFAULT_OPTIONS.maxDepth,
        maxNodes: options.maxNodes ?? DEFAULT_OPTIONS.maxNodes,
        maxTextLength: options.maxTextLength ?? DEFAULT_OPTIONS.maxTextLength,
    }

    const root = doc.body ?? doc.documentElement
    const state: SerializeState = { nodeCount: 0, truncated: false }
    const tree = root ? serializeElement(root, 0, state, opts, win).join('\n') : ''

    return {
        url: win.location?.href ?? '',
        title: doc.title ?? '',
        viewport: {
            width: win.innerWidth || doc.documentElement?.clientWidth || 0,
            height: win.innerHeight || doc.documentElement?.clientHeight || 0,
        },
        tree,
    }
}
