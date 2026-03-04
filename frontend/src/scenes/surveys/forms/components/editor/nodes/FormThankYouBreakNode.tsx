import { Node, mergeAttributes } from '@tiptap/core'
import { Plugin, PluginKey } from '@tiptap/pm/state'
import { NodeViewProps, NodeViewWrapper, ReactNodeViewRenderer } from '@tiptap/react'
import { v4 as uuidv4 } from 'uuid'

// eslint-disable-next-line @typescript-eslint/no-unused-vars
function FormThankYouBreakNodeView(_props: NodeViewProps): JSX.Element {
    return (
        <NodeViewWrapper className="form-thank-you-break">
            <div contentEditable={false} className="form-thank-you-break__inner">
                <div className="form-thank-you-break__line" />
                <span className="form-thank-you-break__label">Thank you page</span>
                <div className="form-thank-you-break__line" />
            </div>
        </NodeViewWrapper>
    )
}

export const FormThankYouBreakNode = Node.create({
    name: 'formThankYouBreak',

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
        }
    },

    parseHTML() {
        return [{ tag: 'div[data-form-thank-you-break]' }]
    },

    renderHTML({ HTMLAttributes }) {
        return ['div', mergeAttributes({ 'data-form-thank-you-break': '' }, HTMLAttributes)]
    },

    addNodeView() {
        return ReactNodeViewRenderer(FormThankYouBreakNodeView)
    },

    addProseMirrorPlugins() {
        return [
            new Plugin({
                key: new PluginKey('thankYouBreakGuard'),
                filterTransaction: (tr) => {
                    if (!tr.docChanged) {
                        return true
                    }
                    let count = 0
                    tr.doc.forEach((node) => {
                        if (node.type.name === 'formThankYouBreak') {
                            count++
                        }
                    })
                    return count <= 1
                },
            }),
        ]
    },

    addCommands() {
        return {
            insertThankYouBreak:
                () =>
                ({ commands, state }) => {
                    // Only allow one thank you break
                    let hasExisting = false
                    state.doc.forEach((node) => {
                        if (node.type.name === 'formThankYouBreak') {
                            hasExisting = true
                        }
                    })
                    if (hasExisting) {
                        return false
                    }
                    // Insert at the end of the document
                    return commands.insertContentAt(state.doc.content.size, [
                        {
                            type: this.name,
                            attrs: { pageId: uuidv4() },
                        },
                        {
                            type: 'paragraph',
                        },
                    ])
                },
        }
    },
})

declare module '@tiptap/core' {
    interface Commands<ReturnType> {
        formThankYouBreak: {
            insertThankYouBreak: () => ReturnType
        }
    }
}
