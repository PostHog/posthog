import { mergeAttributes, Node } from '@tiptap/core'
import { NotebookNodeType } from '~/types'

export const NotebookNodeTimestampList = Node.create({
    name: NotebookNodeType.TimestampList,
    group: 'block list',

    addOptions() {
        return {
            itemTypeName: NotebookNodeType.TimestampItem,
            HTMLAttributes: {},
        }
    },

    content() {
        return `${this.options.itemTypeName}+`
    },

    parseHTML() {
        return [{ tag: `ul[data-type="${this.name}"]`, priority: 51 }]
    },

    renderHTML({ HTMLAttributes }) {
        return ['ul', mergeAttributes(this.options.HTMLAttributes, HTMLAttributes, { 'data-type': this.name }), 0]
    },
})
