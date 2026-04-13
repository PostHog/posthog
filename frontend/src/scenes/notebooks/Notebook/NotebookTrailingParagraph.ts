import { Extension } from '@tiptap/core'
import { Plugin, PluginKey, TextSelection } from '@tiptap/pm/state'

/**
 * Notion-like behavior: clicking in empty space below the last block
 * creates a new empty paragraph and focuses it. If the last node is
 * already an empty paragraph, it just focuses that one.
 */
export const NotebookTrailingParagraph = Extension.create({
    name: 'notebookTrailingParagraph',

    addProseMirrorPlugins() {
        return [
            new Plugin({
                key: new PluginKey('notebookTrailingParagraph'),
                props: {
                    handleDOMEvents: {
                        mousedown: (view, event) => {
                            if (!view.editable) {
                                return false
                            }

                            const lastChild = view.dom.lastElementChild
                            if (!lastChild) {
                                return false
                            }

                            if (event.clientY <= lastChild.getBoundingClientRect().bottom) {
                                return false
                            }

                            event.preventDefault()

                            const { doc, tr, schema } = view.state
                            const lastNode = doc.lastChild

                            if (lastNode?.type.name === 'paragraph' && lastNode.content.size === 0) {
                                // Empty paragraph already exists - just focus it
                                view.dispatch(tr.setSelection(TextSelection.create(doc, doc.content.size - 1)))
                            } else {
                                // Insert a new empty paragraph and focus it
                                const endPos = doc.content.size
                                tr.insert(endPos, schema.nodes.paragraph.create())
                                tr.setSelection(TextSelection.create(tr.doc, endPos + 1))
                                view.dispatch(tr)
                            }

                            view.focus()
                            return true
                        },
                    },
                },
            }),
        ]
    },
})
