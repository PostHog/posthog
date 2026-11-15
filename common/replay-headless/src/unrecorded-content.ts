import type { ReplayPlugin } from 'posthog-js/rrweb'
import { EventType, IncrementalSource, type eventWithTime } from 'posthog-js/rrweb-types'

/** Marks a replayed element the recording holds no content for, so the style rule can label it. */
export const UNRECORDED_ATTRIBUTE = 'data-ph-unrecorded'

type UnrecordedKind = 'embed' | 'canvas' | 'video' | 'document'

const LABELS: Record<UnrecordedKind, string> = {
    embed: 'Embedded page from another site, not recorded',
    canvas: 'Canvas, not recorded',
    video: 'Video, not recorded',
    document: 'Embedded document, not recorded',
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
    ruleFor(`video[${UNRECORDED_ATTRIBUTE}="video"]`, 'video'),
    // Chrome forces native controls on media in a scriptless document, and their loading overlay covers the label.
    `video[${UNRECORDED_ATTRIBUTE}="video"]::-webkit-media-controls { display: none !important; }`,
    ruleFor(`:is(embed, object)[${UNRECORDED_ATTRIBUTE}="document"]`, 'document'),
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

const IMAGE_URL = /\.(svg|png|jpe?g|gif|webp|avif)([?#]|$)/i

/** An image in an embed or object still loads in the replay, and a transparent one would show the label through it. */
function isImageDocument(element: Element): boolean {
    const url = element.getAttribute('src') ?? element.getAttribute('data') ?? ''
    return (element.getAttribute('type') ?? '').startsWith('image/') || IMAGE_URL.test(url)
}

/**
 * Labels the elements a replay can only show as blank: a cross-origin iframe whose page was not recorded, a canvas
 * the recording holds no pixels for, and every video, embed and object, whose media the rasterizer never loads.
 * Without a label the blank area reads as content that failed to load.
 */
export function UnrecordedContentPlugin(events: eventWithTime[]): ReplayPlugin {
    const { drawnCanvasIds, attachedIframeIds } = scanRecordedContent(events)
    return {
        onBuild: (node, { id, replayer }) => {
            const element = node as Element
            if (node.nodeName === 'VIDEO') {
                // A poster paints over the label, and a still frame that never plays reads as a stuck player.
                element.removeAttribute('poster')
                element.setAttribute(UNRECORDED_ATTRIBUTE, 'video')
                return
            }
            if (node.nodeName === 'EMBED' || node.nodeName === 'OBJECT') {
                if (!isImageDocument(element)) {
                    element.setAttribute(UNRECORDED_ATTRIBUTE, 'document')
                }
                return
            }
            if (node.nodeName !== 'IFRAME' && node.nodeName !== 'CANVAS') {
                return
            }
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
