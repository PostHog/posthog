import { Mark, mergeAttributes } from '@tiptap/core'
import { externalLinkPasteRule, posthogLinkPasteRule } from '../Nodes/utils'
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
        return [posthogLinkPasteRule(this.editor), externalLinkPasteRule(this.editor)]
    },

    addProseMirrorPlugins() {
        return [
            new Plugin({
                key: new PluginKey('handleClickLink'),
                props: {
                    // handleDOMEvents: {
                    //     click(_, event) {
                    //         if (event.button !== 0) {
                    //             return false
                    //         }

                    //         const link = (event.target as HTMLElement)?.closest('a')

                    //         window.open(link?.href)

                    //         // handleClickLink({
                    //         //     to: link?.href,
                    //         //     event: event,
                    //         //     target: link?.target,
                    //         // })

                    //         // openNotebook(id, NotebookTarget.Sidebar)

                    //         return true
                    //     },
                    // },

                    handleClick: (view, _, event) => {
                        if (event.button !== 0) {
                            return false
                        }

                        // const attrs = getAttributes(view.state, this.name)
                        // const link = (event.target as HTMLElement)?.closest('a')

                        // const href = link?.href ?? attrs.href
                        // const target = link?.target ?? attrs.target

                        // event.preventDefault()
                        // event.stopPropagation()
                        // return true
                        // const attrs = getAttributes(view.state, options.type.name)
                        // const link = (event.target as HTMLElement)?.closest('a')
                        // const href = link?.href ?? attrs.href
                        // const target = link?.target ?? attrs.target
                        // if (link && href) {
                        //     window.open(href, target)
                        //     return true
                        // }
                        // return false
                    },
                },
            }),
        ]
    },
})

const isPostHogLink = (href: string): boolean => {
    return new URL(href, window.location.origin).origin === window.location.origin
}
