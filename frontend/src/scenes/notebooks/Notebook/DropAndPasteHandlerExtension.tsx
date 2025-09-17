import { Plugin, PluginKey } from '@tiptap/pm/state'
import { Extension } from '@tiptap/react'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import { NotebookNodeType } from '../types'

export const DropAndPasteHandlerExtension = Extension.create({
    name: 'DropAndPasteHandlerExtension',

    addProseMirrorPlugins() {
        return [
            new Plugin({
                key: new PluginKey(this.name),
                props: {
                    handleDrop: (view, event, _slice, moved) => {
                        if (!this.editor) {
                            return false
                        }

                        if (!moved && event.dataTransfer) {
                            const text = event.dataTransfer.getData('text/plain')
                            const node = event.dataTransfer.getData('node')
                            const properties = event.dataTransfer.getData('properties')

                            if (text.indexOf(window.location.origin) === 0 || node) {
                                // PostHog link - ensure this gets input as a proper link
                                const coordinates = view.posAtCoords({ left: event.clientX, top: event.clientY })

                                if (!coordinates) {
                                    return false
                                }

                                if (node) {
                                    this.editor
                                        .chain()
                                        .focus()
                                        .setTextSelection(coordinates.pos)
                                        .insertContent({ type: node, attrs: JSON.parse(properties) })
                                        .run()

                                    // We report this case, the pasted version is handled by the posthogNodePasteRule
                                    posthog.capture('notebook node dropped', { node_type: node })
                                } else {
                                    this.editor?.chain().focus().setTextSelection(coordinates.pos).run()
                                    view.pasteText(text)
                                }

                                return true
                            }

                            if (!moved && event.dataTransfer.files && event.dataTransfer.files.length > 0) {
                                const coordinates = view.posAtCoords({
                                    left: event.clientX,
                                    top: event.clientY,
                                })

                                if (!coordinates) {
                                    // TODO: Seek to end of document instead
                                    return true
                                }

                                // if dropping external files
                                const fileList = Array.from(event.dataTransfer.files)
                                const contentToAdd: any[] = []
                                for (const file of fileList) {
                                    if (file.type.startsWith('image/')) {
                                        contentToAdd.push({
                                            type: NotebookNodeType.Image,
                                            attrs: { file },
                                        })
                                    } else {
                                        lemonToast.warning('Only images can be added to Notebooks at this time.')
                                    }
                                }

                                this.editor
                                    .chain()
                                    .focus()
                                    .setTextSelection(coordinates.pos)
                                    .insertContent(contentToAdd)
                                    .run()
                                posthog.capture('notebook files dropped', {
                                    file_types: fileList.map((x) => x.type),
                                })

                                return true
                            }
                        }

                        return false
                    },

                    handlePaste: (_view, event) => {
                        if (!this.editor) {
                            return false
                        }

                        // Special handling for pasting files such as images
                        if (event.clipboardData && event.clipboardData.files?.length > 0) {
                            // iterate over the clipboard files and add any supported file types
                            const fileList = Array.from(event.clipboardData.files)
                            const contentToAdd: any[] = []
                            for (const file of fileList) {
                                if (file.type.startsWith('image/')) {
                                    contentToAdd.push({
                                        type: NotebookNodeType.Image,
                                        attrs: { file },
                                    })
                                } else {
                                    lemonToast.warning('Only images can be added to Notebooks at this time.')
                                }
                            }

                            this.editor.chain().focus().insertContent(contentToAdd).run()
                            posthog.capture('notebook files pasted', {
                                file_types: fileList.map((x) => x.type),
                            })

                            return true
                        }
                    },
                },
            }),
        ]
    },
})
