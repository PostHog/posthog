import { Mark, getMarkRange, mergeAttributes } from '@tiptap/core'
import { Plugin, PluginKey } from '@tiptap/pm/state'

import { linkPasteRule } from '../Nodes/utils'

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
        const href = HTMLAttributes.href || ''
        const target = isPostHogLink(href) ? undefined : '_blank'
        if (!isSafeProtocol(href)) {
            HTMLAttributes.href = ''
        }
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

                                if (href && isSafeProtocol(href)) {
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

const SAFE_LINK_PROTOCOLS = /^(https?:|mailto:)/i

export const isSafeProtocol = (href: string): boolean => {
    return SAFE_LINK_PROTOCOLS.test(href)
}

const isPostHogLink = (href: string): boolean => {
    try {
        const url = new URL(href, window.location.origin)
        return url.origin === window.location.origin
    } catch {
        return false
    }
}
