import './DraggableTextNodes.scss'

import Heading from '@tiptap/extension-heading'
import Paragraph from '@tiptap/extension-paragraph'
import { Node as PMNode } from '@tiptap/pm/model'
import { Plugin, PluginKey } from '@tiptap/pm/state'
import { Decoration, DecorationSet } from '@tiptap/pm/view'
import { Editor, ReactRenderer } from '@tiptap/react'

import { IconDragHandle } from 'lib/lemon-ui/icons'

import { CollapsibleHeading } from './CollapsibleHeading'

function DragHandle(): JSX.Element {
    return (
        <div className="draggable-text-node__drag-handle" data-drag-handle contentEditable={false}>
            <IconDragHandle className="cursor-move text-base shrink-0" />
        </div>
    )
}

function createDecorations(doc: PMNode, nodeTypes: string[], editor: Editor): DecorationSet {
    const decorations: Decoration[] = []

    doc.descendants((node, pos) => {
        if (nodeTypes.includes(node.type.name)) {
            const renderer = new ReactRenderer(DragHandle, {
                editor,
                props: {},
            })
            decorations.push(Decoration.widget(pos + 1, renderer.element, { side: -1 }))
        }
    })

    return DecorationSet.create(doc as any, decorations)
}

export const DraggableHeading = Heading.extend({
    draggable: true,

    addProseMirrorPlugins() {
        const pluginKey = new PluginKey('dragHandleHeading')
        return [
            new Plugin({
                key: pluginKey,
                state: {
                    init: (_, { doc }) => createDecorations(doc, ['heading'], this.editor),
                    apply: (tr, old) => {
                        if (tr.docChanged || tr.selectionSet) {
                            return createDecorations(tr.doc as PMNode, ['heading'], this.editor)
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
})

export const DraggableCollapsibleHeading = CollapsibleHeading.extend({
    draggable: true,

    addProseMirrorPlugins() {
        const pluginKey = new PluginKey('dragHandleCollapsibleHeading')
        const parentPlugins = this.parent?.() || []
        return [
            ...parentPlugins,
            new Plugin({
                key: pluginKey,
                state: {
                    init: (_, { doc }) => createDecorations(doc, ['heading'], this.editor),
                    apply: (tr, old) => {
                        if (tr.docChanged || tr.selectionSet) {
                            return createDecorations(tr.doc as PMNode, ['heading'], this.editor)
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
})

export const DraggableParagraph = Paragraph.extend({
    draggable: true,

    addProseMirrorPlugins() {
        const pluginKey = new PluginKey('dragHandleParagraph')
        return [
            new Plugin({
                key: pluginKey,
                state: {
                    init: (_, { doc }) => createDecorations(doc, ['paragraph'], this.editor),
                    apply: (tr, old) => {
                        if (tr.docChanged || tr.selectionSet) {
                            return createDecorations(tr.doc as PMNode, ['paragraph'], this.editor)
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
})
