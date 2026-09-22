import type { JSONContent } from '@tiptap/core'

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

export function getImageOnlyTextCardImage(
    converter: TiptapMarkdownConverter,
    markdown: string | null | undefined
): ImageTileImage | null {
    const cacheKey = markdown ?? ''
    if (imageOnlyTextCardImageCache.has(cacheKey)) {
        return imageOnlyTextCardImageCache.get(cacheKey) ?? null
    }

    let doc: JSONContent
    try {
        doc = converter.markdownToDoc(markdown)
    } catch {
        cacheImageOnlyTextCardImage(cacheKey, null)
        return null
    }

    let image: ImageTileImage | null = null
    let imageCount = 0
    let hasOtherContent = false

    const visit = (node: JSONContent): void => {
        if (node.type === 'image') {
            imageCount += 1
            const parsedImage = getImageTile(node)
            if (parsedImage) {
                image = parsedImage
            } else {
                hasOtherContent = true
            }
            return
        }

        if (node.type === 'text') {
            if (node.text?.trim()) {
                hasOtherContent = true
            }
            return
        }

        if (node.type === 'doc' || node.type === 'paragraph') {
            node.content?.forEach(visit)
            return
        }

        hasOtherContent = true
    }

    visit(doc)

    const result = imageCount === 1 && !hasOtherContent ? image : null
    cacheImageOnlyTextCardImage(cacheKey, result)

    return result
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

function getImageTile(node: JSONContent): ImageTileImage | null {
    const src = String(node.attrs?.src ?? '').trim()
    if (!src) {
        return null
    }

    return {
        src,
        alt: String(node.attrs?.alt ?? ''),
        title: String(node.attrs?.title ?? ''),
        layout: getImageTileLayout(node.attrs?.layout),
        position: getImageTilePosition(node.attrs?.position),
        width: node.attrs?.width,
        height: node.attrs?.height,
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
