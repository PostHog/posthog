import { captureElementSvg } from 'lib/utils/captureElementImage'

/** Marks the feedback widget's own nodes, so the screenshot leaves them out. */
export const INTERNAL_FEEDBACK_IGNORE_ATTR = 'data-internal-feedback-ignore'

const SCROLL_ATTR = 'data-internal-feedback-scroll'
const SVG_DATA_URL_PREFIX = 'data:image/svg+xml;charset=utf-8,'
// Same blue and padding as the selected state of the toolbar's ElementHighlight.
const OUTLINE_COLOR = '#1d4aff'
const OUTLINE_PADDING = 4
const OUTLINE_WIDTH = 3

export interface ViewportRect {
    top: number
    left: number
    width: number
    height: number
}

function markScrolledElements(): HTMLElement[] {
    const marked: HTMLElement[] = []
    if (window.scrollX || window.scrollY) {
        document.body.setAttribute(SCROLL_ATTR, `${window.scrollX},${window.scrollY}`)
        marked.push(document.body)
    }
    for (const element of Array.from(document.body.querySelectorAll<HTMLElement>('*'))) {
        if (element.scrollTop || element.scrollLeft) {
            element.setAttribute(SCROLL_ATTR, `${element.scrollLeft},${element.scrollTop}`)
            marked.push(element)
        }
    }
    return marked
}

function readStyle(style: string, property: string): string | null {
    const match = style.match(new RegExp(`(?:^|;)\\s*${property}:\\s*([^;]+)`))
    return match ? match[1].trim() : null
}

/**
 * html-to-image clones every scroll container at scroll position zero, so content scrolled out of
 * view would appear in the screenshot instead of what the person saw. Shift the children of each
 * marked container back by its scroll offset. Fixed and sticky children stay put, because the
 * browser already drew them relative to the viewport or the container edge.
 */
function applyScrollOffsets(svgDataUrl: string): string {
    const svg = decodeURIComponent(svgDataUrl.slice(SVG_DATA_URL_PREFIX.length))
    const doc = new DOMParser().parseFromString(svg, 'image/svg+xml')
    for (const container of Array.from(doc.querySelectorAll(`[${SCROLL_ATTR}]`))) {
        const [left, top] = (container.getAttribute(SCROLL_ATTR) ?? '0,0').split(',').map(Number)
        for (const child of Array.from(container.children)) {
            const style = child.getAttribute('style') ?? ''
            const position = readStyle(style, 'position')
            if (position === 'fixed' || position === 'sticky') {
                continue
            }
            const transform = readStyle(style, 'transform')
            const shift = `translate(${-left}px, ${-top}px)`
            child.setAttribute(
                'style',
                `${style}; transform: ${transform && transform !== 'none' ? `${shift} ${transform}` : shift};`
            )
        }
    }
    return SVG_DATA_URL_PREFIX + encodeURIComponent(new XMLSerializer().serializeToString(doc))
}

function loadImage(src: string): Promise<HTMLImageElement> {
    return new Promise((resolve, reject) => {
        const image = new Image()
        image.onload = () => resolve(image)
        image.onerror = () => reject(new Error('Could not render the page screenshot'))
        image.src = src
    })
}

/**
 * Captures what the person sees in the viewport, with the selected element outlined when there is one. The capture
 * starts at <body> rather than the app root, because menus, popovers and modals render in portals
 * outside the root.
 */
export async function captureFeedbackScreenshot(rect: ViewportRect | null): Promise<Blob> {
    const width = window.innerWidth
    const height = window.innerHeight
    const pixelRatio = Math.min(window.devicePixelRatio || 1, 2)

    const marked = markScrolledElements()
    let svgDataUrl: string
    try {
        svgDataUrl = await captureElementSvg(document.body, {
            width,
            height,
            backgroundColor: getComputedStyle(document.body).backgroundColor,
            filter: (node) => !(node instanceof HTMLElement && node.hasAttribute(INTERNAL_FEEDBACK_IGNORE_ATTR)),
        })
    } finally {
        for (const element of marked) {
            element.removeAttribute(SCROLL_ATTR)
        }
    }

    const image = await loadImage(applyScrollOffsets(svgDataUrl))
    const canvas = document.createElement('canvas')
    canvas.width = Math.round(width * pixelRatio)
    canvas.height = Math.round(height * pixelRatio)
    const context = canvas.getContext('2d')
    if (!context) {
        throw new Error('Could not get a 2D canvas context for the screenshot')
    }
    context.drawImage(image, 0, 0, canvas.width, canvas.height)
    if (rect) {
        context.strokeStyle = OUTLINE_COLOR
        context.lineWidth = OUTLINE_WIDTH * pixelRatio
        context.strokeRect(
            (rect.left - OUTLINE_PADDING) * pixelRatio,
            (rect.top - OUTLINE_PADDING) * pixelRatio,
            (rect.width + OUTLINE_PADDING * 2) * pixelRatio,
            (rect.height + OUTLINE_PADDING * 2) * pixelRatio
        )
    }

    return await new Promise((resolve, reject) => {
        canvas.toBlob(
            (blob) => (blob ? resolve(blob) : reject(new Error('Encoding the screenshot produced no data'))),
            'image/jpeg',
            0.85
        )
    })
}
