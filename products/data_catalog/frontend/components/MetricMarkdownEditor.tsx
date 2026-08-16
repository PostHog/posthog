import type { Editor } from '@tiptap/core'
import { Placeholder } from '@tiptap/extension-placeholder'
import { PluginKey } from '@tiptap/pm/state'
import { Extensions } from '@tiptap/react'
import { useActions } from 'kea'
import { useRef, useState } from 'react'

import { createInlineMarkdownSlashCommandsExtension } from 'lib/components/MarkdownEditor/inline/inlineMarkdownSlashCommands'
import { RichMarkdownEditor } from 'lib/components/MarkdownEditor/rich/RichMarkdownEditor'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { LemonTextAreaMarkdown } from 'lib/lemon-ui/LemonTextArea/LemonTextAreaMarkdown'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'

import { METRIC_MARKDOWN_MAX_LENGTH } from '../common'
import { CatalogReferencePickerModal } from './CatalogReferencePickerModal'
import { METRIC_MARKDOWN_EXTENSIONS, metricMarkdownConverter } from './metricMarkdown'
import {
    CatalogReferenceKind,
    CatalogReferencePickerHost,
    createMetricMarkdownSlashCommands,
    insertCatalogReference,
} from './metricMarkdownSlashCommands'

const METRIC_MARKDOWN_SLASH_COMMANDS_PLUGIN_KEY = new PluginKey('metricMarkdownSlashCommands')

export interface MetricMarkdownEditorProps {
    value: string | undefined
    onChange: (value: string) => void
}

export function MetricMarkdownEditor({ value, onChange }: MetricMarkdownEditorProps): JSX.Element {
    // Decided once on mount: agent-authored definitions can contain markdown the rich schema
    // drops, and editing those in ProseMirror would silently rewrite the saved definition,
    // so they stay on the plain textarea.
    const [useLegacyEditor] = useState(() => !metricMarkdownConverter.isRoundTripSafe(value))
    const [pickerState, setPickerState] = useState<{ kind: CatalogReferenceKind; editor: Editor } | null>(null)
    const pickerHostRef = useRef<CatalogReferencePickerHost | null>(null)
    const { loadDatabase } = useActions(databaseTableListLogic)

    pickerHostRef.current = {
        open: (kind, editor) => {
            if (kind === 'table') {
                loadDatabase({})
            }
            setPickerState({ kind, editor })
        },
    }

    // Built once per mount: the slash extension captures the host ref, which stays stable.
    const [editorExtensions] = useState<Extensions>(() => [
        ...METRIC_MARKDOWN_EXTENSIONS,
        Placeholder.configure({
            placeholder: 'Describe how to calculate this metric, step by step. Type / for commands',
        }),
        createInlineMarkdownSlashCommandsExtension(
            METRIC_MARKDOWN_SLASH_COMMANDS_PLUGIN_KEY,
            createMetricMarkdownSlashCommands(pickerHostRef)
        ),
    ])

    if (useLegacyEditor) {
        return (
            <LemonTextAreaMarkdown
                value={value}
                onChange={onChange}
                maxLength={METRIC_MARKDOWN_MAX_LENGTH}
                minRows={8}
                maxRows={30}
                data-attr="data-catalog-metric-markdown-editor-legacy"
            />
        )
    }

    return (
        <>
            <RichMarkdownEditor
                value={value}
                onChange={onChange}
                minRows={8}
                maxRows={30}
                maxLength={METRIC_MARKDOWN_MAX_LENGTH}
                dataAttr="data-catalog-metric-markdown-editor"
                extensions={editorExtensions}
                markdownToDoc={metricMarkdownConverter.markdownToDoc}
                docToMarkdown={metricMarkdownConverter.docToMarkdown}
                renderPreview={(markdown) => <LemonMarkdown disableImages>{markdown}</LemonMarkdown>}
                controls={{ imageUpload: false }}
                tabs={['write', 'preview']}
                autoFocus
            />
            {pickerState && (
                <CatalogReferencePickerModal
                    kind={pickerState.kind}
                    onSelect={(name) => {
                        insertCatalogReference(pickerState.editor, name)
                        setPickerState(null)
                    }}
                    onClose={() => setPickerState(null)}
                />
            )}
        </>
    )
}
