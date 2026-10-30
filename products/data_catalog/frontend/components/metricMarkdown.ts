import { Extension, JSONContent } from '@tiptap/core'
import { Slice } from '@tiptap/pm/model'
import { Plugin, PluginKey } from '@tiptap/pm/state'
import type { EditorProps } from '@tiptap/pm/view'

import { MARKDOWN_BASE_EDITABLE_EXTENSIONS } from 'lib/components/MarkdownEditor/shared/markdownExtensions'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { createTiptapMarkdownConverter } from 'lib/utils/markdown'

// No Image extension: definitions render with `disableImages` and agents consume the raw
// markdown, so an uploaded image would have no surface anywhere downstream.
export const METRIC_MARKDOWN_EXTENSIONS = [...MARKDOWN_BASE_EDITABLE_EXTENSIONS]

export const metricMarkdownConverter = createTiptapMarkdownConverter(METRIC_MARKDOWN_EXTENSIONS)

const MARKDOWN_BLOCK_SYNTAX = /^\s{0,3}(#{1,6}\s|[-*+]\s|\d+[.)]\s|>\s?|```|\|)/m

const METRIC_MARKDOWN_PASTE_PLUGIN_KEY = new PluginKey('metricMarkdownPaste')

export type MarkdownPasteResult = { kind: 'formatted'; doc: JSONContent } | { kind: 'plain'; lossy: boolean }

function wordCharacters(text: string): string {
    return text.replace(/[^\p{L}\p{N}]/gu, '')
}

export function parseMarkdownPaste(text: string): MarkdownPasteResult {
    if (!MARKDOWN_BLOCK_SYNTAX.test(text)) {
        return { kind: 'plain', lossy: false }
    }
    const doc = metricMarkdownConverter.markdownToDoc(text)
    const keepsEveryWord = wordCharacters(metricMarkdownConverter.docToMarkdown(doc)) === wordCharacters(text)
    if (!keepsEveryWord || !metricMarkdownConverter.isRoundTripSafe(text)) {
        return { kind: 'plain', lossy: true }
    }
    return { kind: 'formatted', doc }
}

export const MetricMarkdownPaste = Extension.create({
    name: 'metricMarkdownPaste',

    addProseMirrorPlugins() {
        const schema = this.editor.schema
        const parseClipboardText = (text: string): Slice | undefined => {
            const result = parseMarkdownPaste(text)
            if (result.kind === 'formatted') {
                return new Slice(schema.nodeFromJSON(result.doc).content, 0, 0)
            }
            if (result.lossy) {
                lemonToast.info('Some formatting was pasted as plain text.')
            }
            return undefined
        }
        return [
            new Plugin({
                key: METRIC_MARKDOWN_PASTE_PLUGIN_KEY,
                props: { clipboardTextParser: parseClipboardText as EditorProps['clipboardTextParser'] },
            }),
        ]
    },
})
