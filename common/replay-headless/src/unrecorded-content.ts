import type { ReplayPlugin } from 'posthog-js/rrweb'
import { EventType, IncrementalSource, type eventWithTime } from 'posthog-js/rrweb-types'

/** Marks a replayed element the recording holds no content for, so the style rule can label it. */
export const UNRECORDED_ATTRIBUTE = 'data-ph-unrecorded'

type UnrecordedKind = 'embed' | 'canvas'

const LABELS: Record<UnrecordedKind, string> = {
    embed: 'Embedded page from another site, not recorded',
    canvas: 'Canvas, not recorded',
}

function labelImage(text: string): string {
    const svg =
        `<svg xmlns="http://www.w3.org/2000/svg" width="440" height="44">` +
        `<rect width="440" height="44" rx="6" fill="#ffffff" stroke="#6b7280"/>` +
        `<text x="220" y="28" text-anchor="middle" font-family="sans-serif" font-size="17" fill="#374151">${text}</text>` +
        `</svg>`
    return `url("data:image/svg+xml,${encodeURIComponent(svg)}")`
}

function ruleFor(selector: string, kind: UnrecordedKind): string {
    // Drawn as the element's own background, behind anything the replay paints into it. A light
    // color-scheme keeps an empty iframe document transparent even when the page uses a dark one.
    return `${selector} {
        background: ${labelImage(LABELS[kind])} center / min(440px, 100%) auto no-repeat, repeating-linear-gradient(135deg, #f3f4f6 0 12px, #e5e7eb 12px 24px) !important;
        outline: 2px dashed #6b7280 !important;
        outline-offset: -2px !important;
        color-scheme: light !important;
    }`
}

export const UNRECORDED_STYLE_RULES = [
    ruleFor(`iframe[${UNRECORDED_ATTRIBUTE}="embed"]`, 'embed'),
    ruleFor(`canvas[${UNRECORDED_ATTRIBUTE}="canvas"]`, 'canvas'),
    // The replay document runs no scripts, so a canvas renders as its empty fallback content and collapses to
    // nothing. A box sized from the canvas's own attributes gives the label room. The layer lets any page rule
    // win, so a canvas the page hides stays hidden.
    `@layer ph-unrecorded {
        canvas[${UNRECORDED_ATTRIBUTE}="canvas"]:not([hidden]) {
            display: inline-block;
            width: attr(width px, 300px);
            height: attr(height px, 150px);
        }
    }`,
]

interface RecordedContent {
    /** Canvases the recording has pixels for: a drawing command or a snapshot image set by a mutation. */
    drawnCanvasIds: Set<number>
    /** Cross-origin iframes whose page was recorded too, because the customer enabled cross-origin iframe recording. */
    attachedIframeIds: Set<number>
}

export function scanRecordedContent(events: eventWithTime[]): RecordedContent {
    const drawnCanvasIds = new Set<number>()
    const attachedIframeIds = new Set<number>()
    for (const event of events) {
        if (event.type !== EventType.IncrementalSnapshot) {
            continue
        }
        const data = event.data
        if (data.source === IncrementalSource.CanvasMutation) {
            drawnCanvasIds.add(data.id)
        } else if (data.source === IncrementalSource.Mutation) {
            if (data.isAttachIframe) {
                for (const add of data.adds) {
                    attachedIframeIds.add(add.parentId)
                }
            }
            for (const change of data.attributes) {
                if (typeof change.attributes?.rr_dataURL === 'string') {
                    drawnCanvasIds.add(change.id)
                }
            }
        }
    }
    return { drawnCanvasIds, attachedIframeIds }
}

/**
 * Labels the elements a replay can only show as blank: a cross-origin iframe whose page was not recorded, and a
 * canvas the recording holds no pixels for. Without a label the blank area reads as content that failed to load.
 */
export function UnrecordedContentPlugin(events: eventWithTime[]): ReplayPlugin {
    const { drawnCanvasIds, attachedIframeIds } = scanRecordedContent(events)
    return {
        onBuild: (node, { id, replayer }) => {
            if (node.nodeName !== 'IFRAME' && node.nodeName !== 'CANVAS') {
                return
            }
            const element = node as Element
            const meta = replayer.getMirror().getMeta(element as Node)
            const attributes = meta && 'attributes' in meta ? meta.attributes : {}
            if (element.nodeName === 'IFRAME' && attributes.rr_src && !attachedIframeIds.has(id)) {
                element.setAttribute(UNRECORDED_ATTRIBUTE, 'embed')
            } else if (element.nodeName === 'CANVAS' && !attributes.rr_dataURL && !drawnCanvasIds.has(id)) {
                element.setAttribute(UNRECORDED_ATTRIBUTE, 'canvas')
            }
        },
        // An iframe can get its cross-origin `src` after it was built, as a recorded attribute change.
        handler: (event, _isSync, { replayer }) => {
            if (event.type !== EventType.IncrementalSnapshot || event.data.source !== IncrementalSource.Mutation) {
                return
            }
            for (const change of event.data.attributes) {
                if (typeof change.attributes?.rr_src !== 'string' || attachedIframeIds.has(change.id)) {
                    continue
                }
                const node = replayer.getMirror().getNode(change.id)
                if (node?.nodeName === 'IFRAME') {
                    ;(node as Element).setAttribute(UNRECORDED_ATTRIBUTE, 'embed')
                }
            }
        },
    }
}
