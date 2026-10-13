import { Image } from '@tiptap/extension-image'

import { getImageTilePosition, isDefaultImageTilePosition } from './imageTileUtils'
import type { ImageTileLayout, ImageTilePosition } from './imageTileUtils'

function escapeHtmlAttribute(value: string): string {
    return value.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function escapeMarkdownImageAlt(value: string): string {
    return value.replace(/\[/g, '\\[').replace(/\]/g, '\\]')
}

function requiresHtmlImage(alt: string, title: string): boolean {
    return /[\\\r\n]/.test(alt) || /[\\"\r\n]/.test(title)
}

const ImageTileMarkdownExtension = Image.extend({
    addAttributes() {
        return {
            ...this.parent?.(),
            layout: {
                default: null,
                parseHTML: (element: HTMLElement) => (element.getAttribute('data-layout') === 'cover' ? 'cover' : null),
                renderHTML: (attributes: { layout?: ImageTileLayout | null }) =>
                    attributes.layout === 'cover' ? { 'data-layout': 'cover' } : {},
            },
            position: {
                default: null,
                parseHTML: (element: HTMLElement) => {
                    const x = element.getAttribute('data-position-x')
                    const y = element.getAttribute('data-position-y')

                    return x === null || y === null ? null : { x: Number(x), y: Number(y) }
                },
                renderHTML: (attributes: { position?: ImageTilePosition | null }) => {
                    const position = getImageTilePosition(attributes.position)

                    return isDefaultImageTilePosition(position)
                        ? {}
                        : {
                              'data-position-x': String(position.x),
                              'data-position-y': String(position.y),
                          }
                },
            },
        }
    },

    renderMarkdown(node) {
        const attrs = node.attrs || {}
        const src = attrs.src || ''
        const alt = attrs.alt || ''
        const title = attrs.title || ''
        const layout = attrs.layout === 'cover' ? 'cover' : 'contain'
        const position = getImageTilePosition(attrs.position)
        const width = attrs.width
        const height = attrs.height

        const stringAlt = String(alt)
        const stringTitle = String(title)
        const escapedAlt = escapeMarkdownImageAlt(stringAlt)
        const hasCustomPosition = !isDefaultImageTilePosition(position)

        if (
            layout === 'contain' &&
            !width &&
            !height &&
            !hasCustomPosition &&
            !requiresHtmlImage(stringAlt, stringTitle)
        ) {
            return title ? `![${escapedAlt}](${src} "${stringTitle}")` : `![${escapedAlt}](${src})`
        }

        const htmlAttrs = [
            `src="${escapeHtmlAttribute(String(src))}"`,
            `alt="${escapeHtmlAttribute(String(alt))}"`,
            ...(layout === 'cover' ? ['data-layout="cover"'] : []),
            ...(hasCustomPosition ? [`data-position-x="${position.x}"`, `data-position-y="${position.y}"`] : []),
            ...(title ? [`title="${escapeHtmlAttribute(stringTitle)}"`] : []),
            ...(width ? [`width="${escapeHtmlAttribute(String(width))}"`] : []),
            ...(height ? [`height="${escapeHtmlAttribute(String(height))}"`] : []),
        ]

        return `<img ${htmlAttrs.join(' ')} />`
    },
})

export const IMAGE_TILE_MARKDOWN_EDITABLE_EXTENSION = ImageTileMarkdownExtension.configure({
    HTMLAttributes: {
        draggable: 'true',
    },
    resize: {
        enabled: true,
        directions: ['top', 'bottom', 'left', 'right'],
        minWidth: 50,
        minHeight: 50,
        alwaysPreserveAspectRatio: true,
    },
})

export const IMAGE_TILE_MARKDOWN_READONLY_EXTENSION = ImageTileMarkdownExtension.configure({
    HTMLAttributes: {
        draggable: 'false',
    },
    resize: {
        enabled: false,
    },
})
