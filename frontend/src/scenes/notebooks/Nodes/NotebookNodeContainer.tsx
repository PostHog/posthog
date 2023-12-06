import { Node, mergeAttributes } from '@tiptap/core'
import clsx from 'clsx'

export default Node.create({
    name: 'column',
    group: 'block',
    content: '(paragraph|block)*',
    isolating: true,
    selectable: false,
    atom: true,

    renderHTML({ HTMLAttributes, node }) {
        const attrs = mergeAttributes(HTMLAttributes, {
            class: clsx('column grid gap-4', `grid-cols-${node.content.childCount}`),
        })
        return ['div', attrs, 0]
    },
})
