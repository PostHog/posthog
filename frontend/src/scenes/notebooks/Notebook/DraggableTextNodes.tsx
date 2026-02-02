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

/**
 * Finds the range of nodes that should move when dragging a heading.
 * Returns [from, to] positions that include the heading and all content until the next heading of same or higher level.
 */
function findSectionRange(doc: PMNode, headingPos: number): [number, number] | null {
    const headingNode = doc.nodeAt(headingPos)
    if (!headingNode || headingNode.type.name !== 'heading') {
        return null
    }

    const headingLevel = headingNode.attrs.level
    const topNodes: { pos: number; size: number; level?: number }[] = []

    // Collect all top-level nodes with their positions and sizes
    doc.descendants((node, pos, parent) => {
        if (parent === doc) {
            topNodes.push({
                pos,
                size: node.nodeSize,
                level: node.type.name === 'heading' ? node.attrs.level : undefined,
            })
        }
        return false // Don't descend into children
    })

    // Find the index of our heading
    const headingIndex = topNodes.findIndex((n) => n.pos === headingPos)
    if (headingIndex === -1) {
        return null
    }

    // Find the end of the section - next heading of same or higher level
    let endIndex = topNodes.length
    for (let i = headingIndex + 1; i < topNodes.length; i++) {
        const level = topNodes[i].level
        if (level !== undefined && level <= headingLevel) {
            endIndex = i
            break
        }
    }

    // Calculate the range
    const from = headingPos
    const to = endIndex < topNodes.length ? topNodes[endIndex].pos : doc.content.size

    return [from, to]
}

export const DraggableHeading = Heading.extend({
    draggable: true,

    addProseMirrorPlugins() {
        const pluginKey = new PluginKey('dragHandleHeading')
        const sectionDragKey = new PluginKey('sectionDragHeading')

        let draggingSectionRange: [number, number] | null = null

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
            new Plugin({
                key: sectionDragKey,
                props: {
                    handleDOMEvents: {
                        dragstart: (view, event) => {
                            const target = event.target as HTMLElement

                            // The drag is initiated on the heading element itself
                            const headingElement = target.closest('h1, h2, h3, h4, h5, h6')

                            if (!headingElement) {
                                return false
                            }

                            // Get the position before the heading element (not inside it)
                            let pos = view.posAtDOM(headingElement, 0)
                            const $pos = view.state.doc.resolve(pos)

                            // Walk up to find the heading node position
                            for (let d = $pos.depth; d > 0; d--) {
                                const node = $pos.node(d)
                                if (node.type.name === 'heading') {
                                    pos = $pos.before(d)
                                    break
                                }
                            }

                            const node = view.state.doc.nodeAt(pos)

                            if (node && node.type.name === 'heading') {
                                const range = findSectionRange(view.state.doc, pos)

                                if (range) {
                                    draggingSectionRange = range
                                }
                            } else {
                            }
                            return false
                        },
                        dragend: () => {
                            draggingSectionRange = null
                            return false
                        },
                    },
                    handleDrop: (view, event, _slice, moved) => {
                        if (!draggingSectionRange || !moved) {
                            return false
                        }

                        const [from, to] = draggingSectionRange

                        const dropPos = view.posAtCoords({ left: event.clientX, top: event.clientY })
                        if (!dropPos) {
                            draggingSectionRange = null
                            return false
                        }

                        let insertPos = dropPos.pos
                        const $insertPos = view.state.doc.resolve(insertPos)
                        if ($insertPos.depth > 0) {
                            insertPos = $insertPos.before(1)
                        }

                        if (insertPos > from && insertPos < to) {
                            draggingSectionRange = null
                            return false
                        }

                        const sectionSlice = view.state.doc.slice(from, to)
                        const tr = view.state.tr

                        if (insertPos > to) {
                            tr.insert(insertPos, sectionSlice.content)
                            tr.delete(from, to)
                        } else {
                            tr.delete(from, to)
                            tr.insert(insertPos, sectionSlice.content)
                        }

                        view.dispatch(tr)
                        draggingSectionRange = null
                        return true
                    },
                },
            }),
        ]
    },
})

export const DraggableCollapsibleHeading = CollapsibleHeading.extend({
    draggable: true,

    addProseMirrorPlugins() {
        const pluginKey = new PluginKey('dragHandleCollapsibleHeading')
        const sectionDragKey = new PluginKey('sectionDragCollapsibleHeading')
        const parentPlugins = this.parent?.() || []

        let draggingSectionRange: [number, number] | null = null

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
            new Plugin({
                key: sectionDragKey,
                props: {
                    handleDOMEvents: {
                        dragstart: (view, event) => {
                            const target = event.target as HTMLElement

                            // The drag is initiated on the heading element itself
                            const headingElement = target.closest('h1, h2, h3, h4, h5, h6')

                            if (!headingElement) {
                                return false
                            }

                            // Get the position before the heading element (not inside it)
                            let pos = view.posAtDOM(headingElement, 0)
                            const $pos = view.state.doc.resolve(pos)

                            // Walk up to find the heading node position
                            for (let d = $pos.depth; d > 0; d--) {
                                const node = $pos.node(d)
                                if (node.type.name === 'heading') {
                                    pos = $pos.before(d)
                                    break
                                }
                            }

                            const node = view.state.doc.nodeAt(pos)

                            if (node && node.type.name === 'heading') {
                                const range = findSectionRange(view.state.doc, pos)

                                if (range) {
                                    draggingSectionRange = range
                                }
                            } else {
                            }
                            return false
                        },
                        dragend: () => {
                            draggingSectionRange = null
                            return false
                        },
                    },
                    handleDrop: (view, event, _slice, moved) => {
                        if (!draggingSectionRange || !moved) {
                            return false
                        }

                        const [from, to] = draggingSectionRange

                        const dropPos = view.posAtCoords({ left: event.clientX, top: event.clientY })
                        if (!dropPos) {
                            draggingSectionRange = null
                            return false
                        }

                        let insertPos = dropPos.pos
                        const $insertPos = view.state.doc.resolve(insertPos)
                        if ($insertPos.depth > 0) {
                            insertPos = $insertPos.before(1)
                        }

                        if (insertPos > from && insertPos < to) {
                            draggingSectionRange = null
                            return false
                        }

                        const sectionSlice = view.state.doc.slice(from, to)
                        const tr = view.state.tr

                        if (insertPos > to) {
                            tr.insert(insertPos, sectionSlice.content)
                            tr.delete(from, to)
                        } else {
                            tr.delete(from, to)
                            tr.insert(insertPos, sectionSlice.content)
                        }

                        view.dispatch(tr)
                        draggingSectionRange = null
                        return true
                    },
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
