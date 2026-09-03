import { ReplayPlugin, Replayer } from 'posthog-js/rrweb'
import { EventType, IncrementalSource, eventWithTime } from 'posthog-js/rrweb-types'

// Firefox serializes `-webkit-box-orient` as `-moz-box-orient`, and rrweb captures that serialized
// form. Other engines drop the `-moz-` name, so `-webkit-line-clamp` has no box orientation to work
// with and stops clamping. The replay then shows all of the text that the person saw truncated.
const MOZ_BOX_ORIENT = '-moz-box-orient'
const WEBKIT_BOX_ORIENT = '-webkit-box-orient'
const MOZ_BOX_ORIENT_PATTERN = /-moz-box-orient(\s*:)/gi

function restoreBoxOrient(css: string): string {
    return css.replace(MOZ_BOX_ORIENT_PATTERN, `${WEBKIT_BOX_ORIENT}$1`)
}

function restoreStyleText(textNode: Node): void {
    const content = textNode.textContent
    if (content?.includes(MOZ_BOX_ORIENT)) {
        textNode.textContent = restoreBoxOrient(content)
    }
}

function restoreStyleElement(styleElement: HTMLStyleElement): void {
    const childNodes = styleElement.childNodes
    for (let i = 0; i < childNodes.length; i++) {
        if (childNodes[i].nodeType === Node.TEXT_NODE) {
            restoreStyleText(childNodes[i])
        }
    }
}

function restoreStyleAttribute(element: HTMLElement): void {
    const style = element.getAttribute('style')
    if (style?.includes(MOZ_BOX_ORIENT)) {
        element.setAttribute('style', restoreBoxOrient(style))
    }
}

// rrweb sends a changed `style` attribute either as the whole attribute string, or as a map of the
// properties that changed. It applies the map with `setProperty`, which ignores the `-moz-` name.
function restoreStyleMutation(element: HTMLElement, style: unknown): void {
    if (typeof style === 'string') {
        restoreStyleAttribute(element)
        return
    }

    if (!style || typeof style !== 'object' || !(MOZ_BOX_ORIENT in style)) {
        return
    }

    const changed = (style as Record<string, unknown>)[MOZ_BOX_ORIENT]
    const [value, priority] = Array.isArray(changed) ? changed : [changed, '']
    if (typeof value === 'string') {
        element.style.setProperty(WEBKIT_BOX_ORIENT, value, priority)
    } else {
        element.style.removeProperty(WEBKIT_BOX_ORIENT)
    }
}

export const BoxOrientPlugin: ReplayPlugin = {
    onBuild: (node) => {
        if (!node) {
            return
        }

        // A stylesheet added after the snapshot arrives as an empty `STYLE` element and then as a
        // separate text node, so the element has no CSS to rewrite when it is built.
        if (node.nodeType === Node.TEXT_NODE) {
            if (node.parentNode?.nodeName === 'STYLE') {
                restoreStyleText(node as Text)
            }
            return
        }

        if (node.nodeType !== Node.ELEMENT_NODE) {
            return
        }

        if (node.nodeName === 'STYLE') {
            restoreStyleElement(node as HTMLStyleElement)
            return
        }

        restoreStyleAttribute(node as HTMLElement)
    },

    handler: (e: eventWithTime, _isSync: boolean, { replayer }: { replayer: Replayer }) => {
        if (e.type !== EventType.IncrementalSnapshot || e.data.source !== IncrementalSource.Mutation) {
            return
        }

        for (const mutation of e.data.attributes || []) {
            const hasStyle = 'style' in mutation.attributes
            const hasCssText = '_cssText' in mutation.attributes
            if (!hasStyle && !hasCssText) {
                continue
            }

            const node = replayer.getMirror().getNode(mutation.id)
            if (node?.nodeType !== Node.ELEMENT_NODE) {
                continue
            }

            // rrweb inlines a `_cssText` mutation by rebuilding the element, and it builds the
            // replacement without the plugins, so the new stylesheet still holds the `-moz-` name.
            if (hasCssText && node.nodeName === 'STYLE') {
                restoreStyleElement(node as HTMLStyleElement)
            }

            if (hasStyle) {
                restoreStyleMutation(node as HTMLElement, mutation.attributes.style)
            }
        }
    },
}
