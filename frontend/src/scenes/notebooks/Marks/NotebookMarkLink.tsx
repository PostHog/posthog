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
                            const link = (event.target as HTMLElement).closest?.('a')
                            if (link) {
                                event.preventDefault()

                                if (event.metaKey) {
                                    const href = link.href
                                    if (href && isSafeProtocol(href)) {
                                        window.open(href, link.target)
                                    }
                                }
                            }
                        },
                    },
                    handleClick(view, pos, event) {
                        if (event.metaKey) {
                            return false
                        }

                        const $pos = view.state.doc.resolve(pos)
                        const range = getMarkRange($pos, markType)
                        if (range) {
                            editor.commands.setTextSelection(range)
                            return true
                        }

                        return false
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
