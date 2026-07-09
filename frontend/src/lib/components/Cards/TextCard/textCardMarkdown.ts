import { Image } from '@tiptap/extension-image'

import {
    MARKDOWN_BASE_EDITABLE_EXTENSIONS,
    MARKDOWN_BASE_READONLY_EXTENSIONS,
} from 'lib/components/MarkdownEditor/shared/markdownExtensions'
import { createTiptapMarkdownConverter } from 'lib/utils/markdown'

function escapeHtmlAttribute(value: string): string {
    return value.replace(/&/g, '&amp;').replace(/"/g, '&quot;')
}

const TextCardImageExtension = Image.extend({
    renderMarkdown(node) {
        const attrs = node.attrs || {}
        const src = attrs.src || ''
        const alt = attrs.alt || ''
        const title = attrs.title || ''
        const width = attrs.width
        const height = attrs.height

        if (!width && !height) {
            return title ? `![${alt}](${src} "${title}")` : `![${alt}](${src})`
        }

        const htmlAttrs = [
            `src="${escapeHtmlAttribute(String(src))}"`,
            `alt="${escapeHtmlAttribute(String(alt))}"`,
            ...(title ? [`title="${escapeHtmlAttribute(String(title))}"`] : []),
            ...(width ? [`width="${escapeHtmlAttribute(String(width))}"`] : []),
            ...(height ? [`height="${escapeHtmlAttribute(String(height))}"`] : []),
        ]

        return `<img ${htmlAttrs.join(' ')} />`
    },
})

export const TEXT_CARD_MARKDOWN_EXTENSIONS = [
    ...MARKDOWN_BASE_EDITABLE_EXTENSIONS,
    TextCardImageExtension.configure({
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
    }),
]

export const TEXT_CARD_MARKDOWN_READONLY_EXTENSIONS = [
    ...MARKDOWN_BASE_READONLY_EXTENSIONS,
    TextCardImageExtension.configure({
        HTMLAttributes: {
            draggable: 'false',
        },
        resize: {
            enabled: false,
        },
    }),
]

export const textCardConverter = createTiptapMarkdownConverter(TEXT_CARD_MARKDOWN_EXTENSIONS)
