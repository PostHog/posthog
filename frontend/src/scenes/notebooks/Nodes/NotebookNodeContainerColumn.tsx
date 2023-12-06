import { Node, mergeAttributes } from '@tiptap/core'

export default Node.create({
    name: 'columnBlock',
    // group: 'block',
    content: 'column',
    isolating: true,
    selectable: true,

    renderHTML({ HTMLAttributes }) {
        const attrs = mergeAttributes(HTMLAttributes, { class: 'column-block' })
        return ['div', attrs, 0]
    },
})
