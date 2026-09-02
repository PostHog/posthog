import type { Editor } from '@tiptap/core'
import type { MutableRefObject } from 'react'

import { IconCode, IconGraph, IconServer } from '@posthog/icons'

import {
    DEFAULT_INLINE_MARKDOWN_SLASH_COMMANDS,
    InlineMarkdownSlashCommandItem,
} from 'lib/components/MarkdownEditor/inline/inlineMarkdownSlashCommands'

export type CatalogReferenceKind = 'metric' | 'table'

export type CatalogReferencePickerHost = {
    open: (kind: CatalogReferenceKind, editor: Editor) => void
}

const CATALOG_SECTION = 'Catalog'

// Image needs an upload host and the metric schema has no image node; Link stays reachable from the toolbar.
const BASE_ITEMS = DEFAULT_INLINE_MARKDOWN_SLASH_COMMANDS.filter((item) => !item.isImagePick && !item.isLinkPopover)

export function insertCatalogReference(editor: Editor, name: string): void {
    editor
        .chain()
        .focus()
        .insertContent([
            { type: 'text', text: name, marks: [{ type: 'code' }] },
            // The trailing space ends the code mark so typing continues as plain text.
            { type: 'text', text: ' ' },
        ])
        .run()
}

export function createMetricMarkdownSlashCommands(
    pickerHostRef: MutableRefObject<CatalogReferencePickerHost | null>
): InlineMarkdownSlashCommandItem[] {
    return [
        ...BASE_ITEMS,
        {
            title: 'SQL block',
            description: 'Fenced SQL code block',
            icon: <IconCode />,
            keywords: ['sql', 'query', 'hogql', 'fence'],
            section: CATALOG_SECTION,
            command: (editor) => editor.chain().focus().setCodeBlock({ language: 'sql' }).run(),
        },
        {
            title: 'Reference metric',
            description: 'Insert the name of a catalog metric',
            icon: <IconGraph />,
            keywords: ['metric', 'reference', 'catalog'],
            section: CATALOG_SECTION,
            command: (editor) => pickerHostRef.current?.open('metric', editor),
        },
        {
            title: 'Reference table',
            description: 'Insert the name of a warehouse table',
            icon: <IconServer />,
            keywords: ['table', 'reference', 'warehouse'],
            section: CATALOG_SECTION,
            command: (editor) => pickerHostRef.current?.open('table', editor),
        },
    ]
}
