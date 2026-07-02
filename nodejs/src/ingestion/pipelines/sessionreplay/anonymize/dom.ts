/** Walks parsed rrweb serialized nodes, scrubbing text content and attributes in place. */
import {
    INLINE_IMAGE_ATTR,
    applyBlur,
    blurInlineImageAttr,
    hasMediaSrcAttr,
    isMediaSrcAttr,
    isMediaTag,
} from './assets'
import { ScrubContext, isObject } from './config'
import { scrubCssImages } from './css'
import { redactEmails, scrubText } from './text'
import { scrubUrl } from './url'

export enum NodeType {
    Document = 0,
    DocumentType = 1,
    Element = 2,
    Text = 3,
    Cdata = 4,
    Comment = 5,
}

type ParentKind = 'script' | 'style' | 'other'
type TagKind = 'script' | 'style' | 'media' | 'other'

type AnyNode = Record<string, unknown>

export function scrubFullSnapshot(ctx: ScrubContext, data: unknown): boolean {
    if (!isObject(data) || !isObject(data.node)) {
        return false
    }
    return walkNode(ctx, data.node, 'other')
}

export function scrubMutation(ctx: ScrubContext, data: unknown): boolean {
    if (!isObject(data)) {
        return false
    }
    let changed = false

    if (Array.isArray(data.texts)) {
        for (const t of data.texts) {
            if (isObject(t) && typeof t.value === 'string') {
                const result = scrubText(ctx, t.value)
                if (result.changed) {
                    t.value = result.value
                    changed = true
                }
            }
        }
    }

    if (Array.isArray(data.attributes)) {
        for (const a of data.attributes) {
            if (isObject(a) && isObject(a.attributes)) {
                const kind: TagKind = hasMediaSrcAttr(a.attributes) ? 'media' : 'other'
                changed = scrubAttrs(ctx, a.attributes, kind) || changed
            }
        }
    }

    if (Array.isArray(data.adds)) {
        for (const added of data.adds) {
            if (isObject(added) && isObject(added.node)) {
                changed = walkNode(ctx, added.node, 'other') || changed
            }
        }
    }

    return changed
}

function walkNode(ctx: ScrubContext, node: AnyNode, parent: ParentKind): boolean {
    let changed = false

    switch (node.type) {
        case NodeType.Element: {
            const kind = classifyTag(typeof node.tagName === 'string' ? node.tagName : '')
            if (isObject(node.attributes)) {
                changed = scrubAttrs(ctx, node.attributes, kind) || changed
            }
            const childParent: ParentKind = kind === 'media' ? 'other' : kind
            if (Array.isArray(node.childNodes)) {
                for (const child of node.childNodes) {
                    if (isObject(child)) {
                        changed = walkNode(ctx, child, childParent) || changed
                    }
                }
            }
            break
        }
        case NodeType.Document: {
            if (Array.isArray(node.childNodes)) {
                for (const child of node.childNodes) {
                    if (isObject(child)) {
                        changed = walkNode(ctx, child, 'other') || changed
                    }
                }
            }
            break
        }
        case NodeType.Text: {
            // Script is code — never touch it.
            if (parent === 'script') {
                return false
            }
            if (parent === 'style' || node.isStyle === true) {
                return scrubCssImages(ctx, node, 'textContent')
            }
            changed = scrubTextContent(ctx, node) || changed
            break
        }
        case NodeType.Comment:
        case NodeType.Cdata: {
            changed = scrubTextContent(ctx, node) || changed
            break
        }
        // DocumentType: nothing.
    }

    return changed
}

function scrubTextContent(ctx: ScrubContext, node: AnyNode): boolean {
    if (typeof node.textContent !== 'string') {
        return false
    }
    const result = scrubText(ctx, node.textContent)
    if (result.changed) {
        node.textContent = result.value
        return true
    }
    return false
}

function classifyTag(tag: string): TagKind {
    const lower = tag.toLowerCase()
    if (lower === 'script') {
        return 'script'
    }
    if (lower === 'style') {
        return 'style'
    }
    if (isMediaTag(tag)) {
        return 'media'
    }
    return 'other'
}

function scrubAttrs(ctx: ScrubContext, attrs: Record<string, unknown>, kind: TagKind): boolean {
    let changed = false

    for (const name of Object.keys(attrs)) {
        if (kind === 'media' && isMediaSrcAttr(name)) {
            continue
        }
        // Inlined rendered pixels (canvas/img `rr_dataURL`): a media tag carrying rr_dataURL is an
        // <img> (static raster → advanced topic path); anything else is a <canvas> (dynamic → cheap).
        if (name === INLINE_IMAGE_ATTR) {
            changed = blurInlineImageAttr(ctx, attrs, name, kind === 'media' ? 'img' : 'canvas') || changed
            continue
        }
        const value = attrs[name]
        // Only string attribute values are scrubbed (objects/numbers/bools are skipped).
        if (typeof value !== 'string') {
            continue
        }
        let result
        if (isUrlAttr(name)) {
            result = scrubUrl(ctx, value)
        } else if (name === 'style') {
            changed = scrubCssImages(ctx, attrs, name) || changed
            continue
        } else if (isUserTextAttr(name)) {
            result = scrubText(ctx, value)
        } else if (isDataAttr(name)) {
            result = dataAttrLooksSensitive(value) ? scrubText(ctx, value) : redactEmails(value)
        } else {
            continue
        }
        if (result.changed) {
            attrs[name] = result.value
            changed = true
        }
    }

    if (kind === 'media') {
        applyBlur(ctx, attrs)
        changed = true
    }

    return changed
}

function isUserTextAttr(name: string): boolean {
    switch (name) {
        case 'alt':
        case 'title':
        case 'placeholder':
        case 'aria-label':
        case 'aria-description':
        case 'aria-roledescription':
        case 'aria-valuetext':
        case 'aria-placeholder':
        case 'value':
        case 'label':
        case 'summary':
            return true
        default:
            return false
    }
}

function isDataAttr(name: string): boolean {
    return name.startsWith('data-') && !name.startsWith('data-anon-original-')
}

function dataAttrLooksSensitive(value: string): boolean {
    // Free text (whitespace) or an email-ish token — not a single enum/state/id token.
    return value.includes('@') || /\s/.test(value)
}

function isUrlAttr(name: string): boolean {
    switch (name) {
        case 'href':
        case 'src':
        case 'srcset':
        case 'action':
        case 'formaction':
        case 'cite':
        case 'data':
        case 'poster':
        case 'background':
        case 'xlink:href':
        case 'manifest':
        case 'longdesc':
            return true
        default:
            return false
    }
}
