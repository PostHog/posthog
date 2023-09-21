import { Mark, getMarkRange, mergeAttributes } from '@tiptap/core'
import { linkPasteRule } from '../Nodes/utils'
import { Plugin, PluginKey } from '@tiptap/pm/state'

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
        return [linkPasteRule()]
    },

    addProseMirrorPlugins() {
        const { editor, type: markType } = this
        return [
            new Plugin({
                key: new PluginKey('handleLinkClick'),
                props: {
                    handleDOMEvents: {
                        click(_, event) {
                            if (event.metaKey) {
                                const link = event.target as HTMLAnchorElement
                                const href = link.href

                                if (href) {
                                    event.preventDefault()
                                    window.open(href, link.target)
                                }
                            } else {
                                const range = getMarkRange(editor.state.selection.$anchor, markType)
                                if (range) {
                                    editor.commands.setTextSelection(range)
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
