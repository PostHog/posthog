import { toBlob } from 'html-to-image'

/** html-to-image does not re-export its options type. */
export type CaptureImageOptions = NonNullable<Parameters<typeof toBlob>[1]>

let cachedStylePropertyNames: string[] | null = null

/**
 * html-to-image copies every property in this list onto every cloned node. Its own default is the full
 * computed style of the document element, which in this app carries several hundred CSS custom properties
 * from the design tokens. Those resolve into the copied values already, so listing them only multiplies the
 * per-node work. The list is the same for every element, so it is built once.
 */
function getStylePropertyNames(): string[] {
    if (cachedStylePropertyNames) {
        return cachedStylePropertyNames
    }
    const names: string[] = []
    const style = getComputedStyle(document.documentElement)
    for (let i = 0; i < style.length; i++) {
        const name = style[i]
        if (!name.startsWith('--')) {
            names.push(name)
        }
    }
    cachedStylePropertyNames = names
    return names
}

/** A 1x1 transparent GIF. */
const BLANK_IMAGE = 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7'

/** Rasterizes a live DOM element to an image blob. Throws when the element renders to nothing. */
export async function captureElementImage(element: HTMLElement, options?: CaptureImageOptions): Promise<Blob> {
    const blob = await toBlob(element, {
        includeStyleProperties: getStylePropertyNames(),
        // html-to-image inlines every image it finds. Its default for one it cannot fetch is an empty
        // `src`, which makes the clone fire `error` and rejects the whole capture with a raw DOM Event.
        imagePlaceholder: BLANK_IMAGE,
        // A resource that answers with something the browser cannot decode fails the same way after
        // the placeholder. Leave that one image blank instead of losing the capture.
        onImageErrorHandler: () => {},
        ...options,
    })

    if (!blob) {
        throw new Error('Rendering the element to an image produced no data')
    }

    return blob
}
