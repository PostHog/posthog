import { Node } from '@tiptap/core'
import { Node as PMNode } from '@tiptap/pm/model'
import { Plugin, PluginKey } from '@tiptap/pm/state'
import { Decoration, DecorationSet } from '@tiptap/pm/view'
import { ReactRenderer } from '@tiptap/react'

import { IconTriangleDownFilled, IconTriangleRightFilled } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

export const NotebookNodeToggleBlock = Node.create({
    name: 'toggleBlock',
    group: 'block',
    content: 'paragraph block*',
    draggable: true,

    addAttributes() {
        return {
            collapsed: {
                default: false,
                parseHTML: (element: HTMLElement) => element.getAttribute('data-collapsed') === 'true',
                renderHTML: (attributes: { collapsed?: boolean }) => ({
                    'data-collapsed': attributes.collapsed ? 'true' : 'false',
                }),
            },
        }
    },

    parseHTML() {
        return [
            {
                tag: 'div[data-type="toggle-block"]',
            },
        ]
    },

    renderHTML({ HTMLAttributes }) {
        return ['div', { 'data-type': 'toggle-block', ...HTMLAttributes }, 0]
    },

    addProseMirrorPlugins() {
        const pluginKey = new PluginKey('toggleBlock')
        return [
            new Plugin({
                key: pluginKey,
                state: {
                    init: (_, { doc }) => createDecorations(doc, this.editor),
                    apply: (tr, old) => {
                        if (tr.docChanged || tr.selectionSet || (tr as any).getMeta('forceDecorations')) {
                            return createDecorations(tr.doc as PMNode, this.editor)
                        }
                        return old
                    },
                },
                props: {
                    decorations: (state) => pluginKey.getState(state),
                },
            }),
        ]
    },

    addCommands() {
        return {
            toggleToggleBlock:
                () =>
                ({ state, dispatch }: any) => {
                    const { selection } = state
                    const node = state.doc.nodeAt(selection.$anchor.pos - selection.$anchor.parentOffset - 1)

                    if (!node || node.type.name !== 'toggleBlock') {
                        return false
                    }

                    const pos = selection.$anchor.pos - selection.$anchor.parentOffset - 1

                    if (dispatch) {
                        const transaction = state.tr.setNodeMarkup(pos, undefined, {
                            ...node.attrs,
                            collapsed: !node.attrs.collapsed,
                        })
                        dispatch(transaction)
                    }

                    return true
                },

            insertToggleBlock:
                () =>
                ({ chain }: any) => {
                    return chain()
                        .insertContent({
                            type: 'toggleBlock',
                            attrs: { collapsed: false },
                            content: [
                                {
                                    type: 'paragraph',
                                },
                            ],
                        })
                        .run()
                },
        } as any
    },

    addKeyboardShortcuts() {
        return {
            // Backspace at the start of an empty toggle block removes it
            Backspace: ({ editor }) => {
                const { selection } = editor.state
                const { $anchor } = selection

                // Check if we're at the start of a toggle block's first paragraph
                if ($anchor.parent.type.name === 'paragraph' && $anchor.parentOffset === 0) {
                    const grandparent = $anchor.node(-1)
                    if (grandparent && grandparent.type.name === 'toggleBlock') {
                        // Check if the paragraph is empty
                        if ($anchor.parent.content.size === 0) {
                            // Check if this is the only child
                            if (grandparent.content.size === $anchor.parent.nodeSize) {
                                // Delete the entire toggle block
                                const start = $anchor.before(-1)
                                const end = start + grandparent.nodeSize
                                editor.chain().deleteRange({ from: start, to: end }).run()
                                return true
                            }
                        }
                    }
                }
                return false
            },
        }
    },
})

function createDecorations(doc: PMNode, editor: any): DecorationSet {
    const decorations: Decoration[] = []

    doc.descendants((node, pos) => {
        if (node.type.name === 'toggleBlock') {
            const collapsed = node.attrs.collapsed

            // Add toggle button decoration at the start of the toggle block
            const renderer = new ReactRenderer(ToggleButton, {
                editor,
                props: {
                    collapsed: !!collapsed,
                    onClick: () => {
                        const transaction = editor.state.tr.setNodeMarkup(pos, undefined, {
                            ...node.attrs,
                            collapsed: !node.attrs.collapsed,
                        })
                        editor.view.dispatch(transaction)
                    },
                },
            })

            // Place the widget at the start of the toggle block
            decorations.push(Decoration.widget(pos + 1, renderer.element, { side: -1 }))

            // Note: CSS handles the hiding of content when collapsed via the data-collapsed attribute
            // We don't need to add decorations for hiding as the CSS rules will handle it
        }
    })

    return DecorationSet.create(doc as any, decorations)
}

function ToggleButton({ collapsed, onClick }: { collapsed: boolean; onClick: () => void }): JSX.Element {
    return (
        <LemonButton
            type="tertiary"
            size="xxsmall"
            tooltip={collapsed ? 'Click to expand' : 'Click to collapse'}
            onClick={onClick}
            icon={collapsed ? <IconTriangleRightFilled /> : <IconTriangleDownFilled />}
            className="toggle-block-button"
        />
    )
}
