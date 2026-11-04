import type { TiptapMarkdownConverter } from 'lib/utils/markdown'

export type ImageTileLayout = 'contain' | 'cover'

export interface ImageTilePosition {
    x: number
    y: number
}

export interface ImageTileImage {
    src: string
    alt: string
    title: string
    layout: ImageTileLayout
    position: ImageTilePosition
    width?: number | string | null
    height?: number | string | null
}

export const DEFAULT_IMAGE_TILE_POSITION: ImageTilePosition = { x: 50, y: 50 }

const IMAGE_TILE_POSITION_MIN = 0
const IMAGE_TILE_POSITION_MAX = 100
const IMAGE_ONLY_TEXT_CARD_CACHE_LIMIT = 100
const imageOnlyTextCardImageCache = new Map<string, ImageTileImage | null>()

function clampImageTilePosition(value: number): number {
    if (!Number.isFinite(value)) {
        return 50
    }

    return Math.max(IMAGE_TILE_POSITION_MIN, Math.min(IMAGE_TILE_POSITION_MAX, value))
}

export function getImageTilePosition(value: unknown): ImageTilePosition {
    const position = value as Partial<ImageTilePosition> | null | undefined

    return {
        x: clampImageTilePosition(Number(position?.x)),
        y: clampImageTilePosition(Number(position?.y)),
    }
}

export function getImageTileLayout(value: ImageTileLayout | null | undefined): ImageTileLayout {
    return value === 'cover' ? 'cover' : 'contain'
}

export function isDefaultImageTilePosition(position: ImageTilePosition): boolean {
    return position.x === DEFAULT_IMAGE_TILE_POSITION.x && position.y === DEFAULT_IMAGE_TILE_POSITION.y
}

export function imageTilePositionToCss(position: ImageTilePosition): string {
    const normalizedPosition = getImageTilePosition(position)
    return `${normalizedPosition.x}% ${normalizedPosition.y}%`
}

// One markdown image: `![alt](src)`, `![alt](<src>)`, either with an optional `"title"`.
// A bare src may hold parentheses nested two deep, such as `diagram(1).png`.
const MARKDOWN_IMAGE =
    /^!\[((?:\\.|[^\\\]])*)\]\((?:<((?:\\.|[^\\<>\n])*)>|(?!<)((?:\\.|[^\s()\\]|\((?:\\.|[^\s()\\]|\((?:\\.|[^\s()\\])*\))*\))+))(?:\s+"((?:\\.|[^"\\])*)")?\)$/
const MARKDOWN_ESCAPE = /\\([!-/:-@[-`{-~])/g

/**
 * Reads the image of a text card whose body is a single image, without the rich text editor,
 * so dashboard layout code can tell image tiles from text tiles before the editor loads.
 */
export function getImageOnlyTextCardImage(markdown: string | null | undefined): ImageTileImage | null {
    const cacheKey = markdown ?? ''
    if (imageOnlyTextCardImageCache.has(cacheKey)) {
        return imageOnlyTextCardImageCache.get(cacheKey) ?? null
    }

    const result = parseImageOnlyMarkdown(cacheKey.trim())
    cacheImageOnlyTextCardImage(cacheKey, result)

    return result
}

function parseImageOnlyMarkdown(body: string): ImageTileImage | null {
    const markdownImage = MARKDOWN_IMAGE.exec(body)
    if (markdownImage) {
        return toImageTile({
            src: (markdownImage[2] ?? markdownImage[3]).replace(MARKDOWN_ESCAPE, '$1'),
            alt: markdownImage[1].replace(MARKDOWN_ESCAPE, '$1'),
            title: markdownImage[4]?.replace(MARKDOWN_ESCAPE, '$1') ?? null,
        })
    }
    if (!body.startsWith('<')) {
        return null
    }

    const images: HTMLImageElement[] = []
    const isImageOnly = (node: Node): boolean => {
        if (node.nodeType === Node.TEXT_NODE) {
            return !node.textContent?.trim()
        }
        if (node instanceof HTMLImageElement) {
            images.push(node)
            return true
        }
        return node instanceof HTMLParagraphElement && Array.from(node.childNodes).every(isImageOnly)
    }
    const { body: htmlBody } = new DOMParser().parseFromString(body, 'text/html')
    if (!Array.from(htmlBody.childNodes).every(isImageOnly) || images.length !== 1) {
        return null
    }

    const [image] = images
    const x = image.getAttribute('data-position-x')
    const y = image.getAttribute('data-position-y')
    return toImageTile({
        src: image.getAttribute('src'),
        alt: image.getAttribute('alt'),
        title: image.getAttribute('title'),
        layout: image.getAttribute('data-layout') === 'cover' ? 'cover' : null,
        position: x === null || y === null ? null : { x: Number(x), y: Number(y) },
        width: image.getAttribute('width'),
        height: image.getAttribute('height'),
    })
}

export function imageTileToMarkdown(
    converter: TiptapMarkdownConverter,
    image: Pick<ImageTileImage, 'src' | 'alt'> & Partial<ImageTileImage>
): string {
    const attrs: Record<string, string | number | ImageTilePosition> = {
        src: image.src,
        alt: image.alt,
    }

    if (image.title) {
        attrs.title = image.title
    }
    if (image.layout === 'cover') {
        attrs.layout = 'cover'
    }
    if (image.position) {
        attrs.position = getImageTilePosition(image.position)
    }
    if (image.width !== undefined && image.width !== null) {
        attrs.width = image.width
    }
    if (image.height !== undefined && image.height !== null) {
        attrs.height = image.height
    }

    return converter.docToMarkdown({
        type: 'doc',
        content: [{ type: 'image', attrs }],
    })
}

interface ImageTileAttributes {
    src: string | null
    alt: string | null
    title: string | null
    layout?: ImageTileLayout | null
    position?: ImageTilePosition | null
    width?: string | null
    height?: string | null
}

function toImageTile(attrs: ImageTileAttributes): ImageTileImage | null {
    const src = (attrs.src ?? '').trim()
    if (!src) {
        return null
    }

    return {
        src,
        alt: attrs.alt ?? '',
        title: attrs.title ?? '',
        layout: getImageTileLayout(attrs.layout),
        position: getImageTilePosition(attrs.position),
        width: attrs.width ?? null,
        height: attrs.height ?? null,
    }
}

function cacheImageOnlyTextCardImage(key: string, image: ImageTileImage | null): void {
    if (imageOnlyTextCardImageCache.size >= IMAGE_ONLY_TEXT_CARD_CACHE_LIMIT) {
        const oldestKey = imageOnlyTextCardImageCache.keys().next().value
        if (oldestKey !== undefined) {
            imageOnlyTextCardImageCache.delete(oldestKey)
        }
    }
    imageOnlyTextCardImageCache.set(key, image)
}
