import { Node, mergeAttributes } from '@tiptap/core'
import { NodeViewProps, NodeViewWrapper, ReactNodeViewRenderer } from '@tiptap/react'
import { useEffect, useState } from 'react'
import { v4 as uuidv4 } from 'uuid'

function computePageNumber(editor: NodeViewProps['editor'], getPos: NodeViewProps['getPos']): number {
    if (!editor || typeof getPos !== 'function') {
        return 2
    }

    const pos = getPos()
    if (typeof pos !== 'number') {
        return 2
    }

    let num = 2

    editor.state.doc.forEach((node, nodePos) => {
        if (node.type.name === 'formPageBreak' && nodePos < pos) {
            num++
        }
    })
    return num
}

function FormPageBreakNodeView({ editor, getPos }: NodeViewProps): JSX.Element {
    const [pageNumber, setPageNumber] = useState(() => computePageNumber(editor, getPos))

    useEffect(() => {
        const onUpdate = (): void => {
            setPageNumber(computePageNumber(editor, getPos))
        }
        editor.on('update', onUpdate)
        return () => {
            editor.off('update', onUpdate)
        }
    }, [editor, getPos])

    return (
        <NodeViewWrapper className="form-page-break">
            <div contentEditable={false} className="form-page-break__inner">
                <div className="form-page-break__line" />
                <span className="form-page-break__label">Page {pageNumber}</span>
                <div className="form-page-break__line" />
            </div>
        </NodeViewWrapper>
    )
}

export const FormPageBreakNode = Node.create({
    name: 'formPageBreak',

    group: 'block',

    atom: true,

    selectable: false,

    draggable: true,

    addAttributes() {
        return {
            pageId: {
                default: null,
                parseHTML: (element: HTMLElement) => element.getAttribute('data-page-id'),
                renderHTML: (attributes: Record<string, unknown>) => ({
                    'data-page-id': attributes.pageId,
                }),
            },
            buttonText: {
                default: 'Next',
                parseHTML: (element: HTMLElement) => element.getAttribute('data-button-text'),
                renderHTML: (attributes: Record<string, unknown>) => ({
                    'data-button-text': attributes.buttonText,
                }),
            },
        }
    },

    parseHTML() {
        return [{ tag: 'div[data-form-page-break]' }]
    },

    renderHTML({ HTMLAttributes }) {
        return ['div', mergeAttributes({ 'data-form-page-break': '' }, HTMLAttributes)]
    },

    addNodeView() {
        return ReactNodeViewRenderer(FormPageBreakNodeView)
    },

    addCommands() {
        return {
            insertPageBreak:
                () =>
                ({ commands }) => {
                    return commands.insertContent([
                        {
                            type: this.name,
                            attrs: { pageId: uuidv4(), buttonText: 'Next' },
                        },
                        { type: 'paragraph' },
                    ])
                },
        }
    },
})

declare module '@tiptap/core' {
    interface Commands<ReturnType> {
        formPageBreak: {
            insertPageBreak: () => ReturnType
        }
    }
}
