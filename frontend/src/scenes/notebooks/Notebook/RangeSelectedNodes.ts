import { Extension } from '@tiptap/core'
import { Plugin, PluginKey } from '@tiptap/pm/state'
import { Decoration, DecorationSet } from '@tiptap/pm/view'

// This plugin decorates atom blocks (insights, sql, python, etc.)
// so they can pick up the same highlight as a directly-selected node.
const pluginKey = new PluginKey('rangeSelectedNodes')

export const RangeSelectedNodes = Extension.create({
    name: 'rangeSelectedNodes',

    addProseMirrorPlugins() {
        return [
            new Plugin({
                key: pluginKey,
                props: {
                    decorations(state) {
                        const { from, to, empty } = state.selection
                        if (empty) {
                            return DecorationSet.empty
                        }
                        const decorations: Decoration[] = []
                        state.doc.nodesBetween(from, to, (node, pos) => {
                            if (!node.isAtom || !node.isBlock) {
                                return true
                            }
                            const nodeFrom = pos
                            const nodeTo = pos + node.nodeSize
                            if (from <= nodeFrom && nodeTo <= to) {
                                decorations.push(
                                    Decoration.node(nodeFrom, nodeTo, {
                                        class: 'NotebookNode--in-selection',
                                    })
                                )
                            }
                            return false
                        })
                        return DecorationSet.create(state.doc, decorations)
                    },
                },
            }),
        ]
    },
})
