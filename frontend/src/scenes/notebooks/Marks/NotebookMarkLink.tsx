import { Mark, mergeAttributes } from '@tiptap/core'
import { externalLinkPasteRule, posthogLinkPasteRule } from '../Nodes/utils'
import { Plugin, PluginKey } from '@tiptap/pm/state'
import { router } from 'kea-router'

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

    addProseMirrorPlugins() {
        return [
            new Plugin({
                key: new PluginKey('handleLinkClick'),
                props: {
                    handleDOMEvents: {
                        click(view, event) {
                            if (event.button !== 0) {
                                return false
                            }

                            const link = event.target as HTMLAnchorElement

                            const href = link.href

                            if (link && href && !view.editable) {
                                event.preventDefault()

                                if (isPostHogLink(href)) {
                                    router.actions.push(link.pathname)
                                } else {
                                    window.open(href, link.target)
                                }
                            }
                        },
                    },
                },
            }),
        ]
    },
})

const isPostHogLink = (href: string): boolean => {
    return new URL(href, window.location.origin).origin === window.location.origin
}
