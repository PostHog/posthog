import { Mark, mergeAttributes } from '@tiptap/core'
import { Plugin, PluginKey } from '@tiptap/pm/state'
// import { notebookLogic } from '../Notebook/notebookLogic'
// import { externalLinkPasteRule } from '../Nodes/utils'

export const LinkMark = Mark.create({
    name: 'link',
    priority: 1000,
    keepOnSplit: false,
    inclusive: true,

    //     addOptions() {
    //         return {
    //             openOnClick: true,
    //             linkOnPaste: true,
    //             HTMLAttributes: {
    //                 target: '_blank',
    //                 rel: 'noopener noreferrer nofollow',
    //             },
    //         }
    //     },

    //     addAttributes() {
    //         return {
    //             href: { default: null },
    //             target: { default: this.options.HTMLAttributes.target },
    //         }
    //     },

    parseHTML() {
        return [{ tag: 'a[href]:not([href *= "javascript:" i])' }]
    },

    renderHTML({ HTMLAttributes }) {
        return ['a', mergeAttributes(this.options.HTMLAttributes, HTMLAttributes), 0]
    },

    //     addPasteRules() {
    //         return [
    //             externalLinkPasteRule({
    //                 find: '(.+)',
    //                 type: this.name,
    //                 getAttributes: (match) => {
    //                     return { href: match[0] }
    //                 },
    //             }),
    //             // markPasteRule({
    //             //     find: (text) =>
    //             //         find(text)
    //             //             .filter((link) => link.isLink)
    //             //             .map((link) => ({
    //             //                 text: link.value,
    //             //                 index: link.start,
    //             //                 data: link,
    //             //             })),
    //             //     type: this.type,
    //             //     getAttributes: (match) => ({
    //             //         href: match.data?.href,
    //             //     }),
    //             // }),
    //         ]
    //     },

    addProseMirrorPlugins() {
        return [
            new Plugin({
                key: new PluginKey('handleClickLink'),
                props: {
                    handleClick: (view, pos, event) => {
                        if (event.button !== 0) {
                            return false
                        }

                        this.editor.isEditable

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

    //     // addProseMirrorPlugins() {
    //     //   const plugins: Plugin[] = []

    //     //   if (this.options.openOnClick) {
    //     //     plugins.push(
    //     //       clickHandler({
    //     //         type: this.type,
    //     //       }),
    //     //     )
    //     //   }

    //     //   if (this.options.linkOnPaste) {
    //     //     plugins.push(
    //     //       pasteHandler({
    //     //         editor: this.editor,
    //     //         type: this.type,
    //     //       }),
    //     //     )
    //     //   }

    //     //   return plugins
    //     // },
})
