import { Node, mergeAttributes } from '@tiptap/core'
import { NodeViewProps, NodeViewWrapper, ReactNodeViewRenderer } from '@tiptap/react'
import clsx from 'clsx'
import { useState } from 'react'

import { WordArtModal } from './WordArtModal'
import {
    DEFAULT_WORD_ART_SIZE,
    DEFAULT_WORD_ART_STYLE,
    normalizeWordArtSize,
    normalizeWordArtStyle,
} from './wordArtPresets'
import { WordArtText } from './WordArtText'

function escapeHtmlText(value: string): string {
    return value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function WordArtNodeView(props: NodeViewProps): JSX.Element {
    const [isModalOpen, setIsModalOpen] = useState(false)
    const { text, style, size } = props.node.attrs
    const isEditable = props.editor.isEditable

    return (
        <NodeViewWrapper
            as="span"
            className={clsx(
                'WordArtNode',
                isEditable && 'WordArtNode--editable',
                props.selected && 'WordArtNode--selected'
            )}
            // No handler while open: the modal is a portal inside this wrapper, so its clicks bubble back here
            onClick={isEditable && !isModalOpen ? () => setIsModalOpen(true) : undefined}
            data-attr="word-art-node"
        >
            <WordArtText text={text} style={style} size={size} />
            {isModalOpen && (
                <WordArtModal
                    onClose={() => setIsModalOpen(false)}
                    initialText={text}
                    initialStyle={style}
                    initialSize={size}
                    onSave={(attrs) => {
                        props.updateAttributes(attrs)
                        setIsModalOpen(false)
                    }}
                />
            )}
        </NodeViewWrapper>
    )
}

export const WordArtExtension = Node.create({
    name: 'wordArt',

    group: 'inline',
    inline: true,
    atom: true,
    selectable: true,

    addAttributes() {
        return {
            text: {
                default: '',
                parseHTML: (element) => element.textContent ?? '',
                renderHTML: () => ({}),
            },
            style: {
                default: DEFAULT_WORD_ART_STYLE,
                parseHTML: (element) => normalizeWordArtStyle(element.getAttribute('data-word-art')),
                renderHTML: (attributes) => ({ 'data-word-art': attributes.style }),
            },
            size: {
                default: DEFAULT_WORD_ART_SIZE,
                parseHTML: (element) => normalizeWordArtSize(element.getAttribute('data-word-art-size')),
                renderHTML: (attributes) =>
                    attributes.size === DEFAULT_WORD_ART_SIZE ? {} : { 'data-word-art-size': attributes.size },
            },
        }
    },

    parseHTML() {
        return [{ tag: 'span[data-word-art]' }]
    },

    renderHTML({ node, HTMLAttributes }) {
        return ['span', mergeAttributes(HTMLAttributes), String(node.attrs.text ?? '')]
    },

    renderMarkdown(node) {
        const style = normalizeWordArtStyle(node.attrs?.style as string)
        const size = normalizeWordArtSize(node.attrs?.size as string)
        const text = String(node.attrs?.text ?? '')
        const sizeAttribute = size === DEFAULT_WORD_ART_SIZE ? '' : ` data-word-art-size="${size}"`
        return `<span data-word-art="${style}"${sizeAttribute}>${escapeHtmlText(text)}</span>`
    },

    addNodeView() {
        return ReactNodeViewRenderer(WordArtNodeView)
    },

    addCommands() {
        return {
            insertWordArt:
                (options: { text: string; style: string; size?: string }) =>
                ({ commands }) => {
                    const text = options.text.trim()
                    if (!text) {
                        return false
                    }
                    return commands.insertContent({
                        type: this.name,
                        attrs: {
                            text,
                            style: normalizeWordArtStyle(options.style),
                            size: normalizeWordArtSize(options.size),
                        },
                    })
                },
        }
    },
})

declare module '@tiptap/core' {
    interface Commands<ReturnType> {
        wordArt: {
            insertWordArt: (options: { text: string; style: string; size?: string }) => ReturnType
        }
    }
}
