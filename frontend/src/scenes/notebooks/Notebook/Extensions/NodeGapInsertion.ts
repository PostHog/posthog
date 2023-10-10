import { Extension } from '@tiptap/core'
import { Plugin, PluginKey } from '@tiptap/pm/state'

const NodeGapInsertionExtension = Extension.create({
    name: 'nodeGapInsertion',

    addProseMirrorPlugins() {
        const { editor } = this
        return [
            new Plugin({
                key: new PluginKey('nodeGapInsertion'),
                props: {
                    handleClick(view, pos, event) {
                        if (!view || !view.editable) {
                            return false
                        }
                        const clickPos = view.posAtCoords({ left: event.clientX, top: event.clientY })
                        const node = editor.state.doc.nodeAt(pos)

                        if (!clickPos || clickPos.inside > -1 || !node) {
                            return false
                        }

                        editor.commands.insertContentAt(pos, { type: 'paragraph', content: [] })
                        return true
                    },
                },
            }),
        ]
    },
})

export default NodeGapInsertionExtension
