import { Mark, mergeAttributes } from '@tiptap/core'
import { externalLinkPasteRule, posthogLinkPasteRule } from '../Nodes/utils'

export const NotebookMarkLink = Mark.create({
    name: 'link',
    priority: 1000,
    keepOnSplit: false,
    inclusive: true,

    addAttributes() {
        return {
            href: { default: null },
            target: { default: undefined },
        }
    },

    parseHTML() {
        return [{ tag: 'a[href]:not([href *= "javascript:" i])' }]
    },

    renderHTML({ HTMLAttributes }) {
        const target = isPostHogLink(HTMLAttributes.href) ? undefined : '_blank'
        return ['a', mergeAttributes(HTMLAttributes, { target }), 0]
    },

    addPasteRules() {
        return [posthogLinkPasteRule(this.editor), externalLinkPasteRule(this.editor)]
    },
})

const isPostHogLink = (href: string): boolean => {
    return new URL(href, window.location.origin).origin === window.location.origin
}
