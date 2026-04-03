import { JSONContent } from '@tiptap/core'
import { Plugin, PluginKey } from '@tiptap/pm/state'
import { Extension } from '@tiptap/react'
import Papa from 'papaparse'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import { NotebookNodeType } from '../types'

export type TabularFormat = 'tsv' | 'csv'

export function detectTabularFormat(text: string): TabularFormat | null {
    const lines = text.replace(/\n+$/, '').split('\n')
    if (lines.length < 2) {
        return null
    }
    if (lines.every((line) => line.includes('\t'))) {
        return 'tsv'
    }
    const commaCounts = lines.map((line) => (line.match(/,/g) || []).length)
    if (commaCounts[0] >= 1 && commaCounts.every((c) => c === commaCounts[0])) {
        return 'csv'
    }
    return null
}

export function isTabularData(text: string): boolean {
    return detectTabularFormat(text) !== null
}

export function parseTabularDataToTipTapTable(text: string, delimiter: string = '\t'): JSONContent {
    const trimmed = text.replace(/\n+$/, '')
    const rows: string[][] =
        delimiter === ','
            ? Papa.parse<string[]>(trimmed, { header: false }).data
            : trimmed.split('\n').map((line) => line.split(delimiter))

    const maxCols = Math.max(...rows.map((row) => row.length))

    const tableRows: JSONContent[] = rows.map((row, rowIndex) => {
        const cellType = rowIndex === 0 ? 'tableHeader' : 'tableCell'
        const cells: JSONContent[] = []
        for (let col = 0; col < maxCols; col++) {
            const value = (row[col] ?? '').trim()
            cells.push({
                type: cellType,
                content: [
                    {
                        type: 'paragraph',
                        content: value ? [{ type: 'text', text: value }] : [],
                    },
                ],
            })
        }
        return { type: 'tableRow', content: cells }
    })

    return { type: 'table', content: tableRows }
}

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

                        // Spreadsheet HTML pastes contain <table> elements that TipTap handles natively
                        // via the table extension, so we only intercept plain-text TSV data
                        const html = event.clipboardData?.getData('text/html')
                        if (html && /<table[\s>]/i.test(html)) {
                            return false
                        }

                        // Detect tab-separated or comma-separated values
                        const text = event.clipboardData?.getData('text/plain')
                        const format = text ? detectTabularFormat(text) : null
                        if (text && format) {
                            const delimiter = format === 'tsv' ? '\t' : ','
                            const tableContent = parseTabularDataToTipTapTable(text, delimiter)
                            const rows = tableContent.content?.length ?? 0
                            const cols = tableContent.content?.[0]?.content?.length ?? 0
                            this.editor.chain().focus().insertContent(tableContent).run()
                            posthog.capture('notebook table pasted', {
                                rows,
                                cols,
                                source: format,
                            })
                            return true
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
