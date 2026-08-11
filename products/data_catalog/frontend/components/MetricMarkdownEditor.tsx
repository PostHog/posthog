import { Placeholder } from '@tiptap/extension-placeholder'
import { Extensions } from '@tiptap/react'
import { useState } from 'react'

import { RichMarkdownEditor } from 'lib/components/MarkdownEditor/rich/RichMarkdownEditor'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { LemonTextAreaMarkdown } from 'lib/lemon-ui/LemonTextArea/LemonTextAreaMarkdown'

import { METRIC_MARKDOWN_MAX_LENGTH } from '../common'
import { METRIC_MARKDOWN_EXTENSIONS, metricMarkdownConverter } from './metricMarkdown'

const METRIC_MARKDOWN_EDITOR_EXTENSIONS: Extensions = [
    ...METRIC_MARKDOWN_EXTENSIONS,
    Placeholder.configure({ placeholder: 'Describe how to calculate this metric, step by step' }),
]

export interface MetricMarkdownEditorProps {
    value: string | undefined
    onChange: (value: string) => void
}

export function MetricMarkdownEditor({ value, onChange }: MetricMarkdownEditorProps): JSX.Element {
    // Decided once on mount: agent-authored definitions can contain markdown the rich schema
    // drops, and editing those in ProseMirror would silently rewrite the saved definition,
    // so they stay on the plain textarea.
    const [useLegacyEditor] = useState(() => !metricMarkdownConverter.isRoundTripSafe(value))

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
        <RichMarkdownEditor
            value={value}
            onChange={onChange}
            minRows={8}
            maxRows={30}
            maxLength={METRIC_MARKDOWN_MAX_LENGTH}
            dataAttr="data-catalog-metric-markdown-editor"
            extensions={METRIC_MARKDOWN_EDITOR_EXTENSIONS}
            markdownToDoc={metricMarkdownConverter.markdownToDoc}
            docToMarkdown={metricMarkdownConverter.docToMarkdown}
            renderPreview={(markdown) => <LemonMarkdown disableImages>{markdown}</LemonMarkdown>}
            controls={{ imageUpload: false }}
            tabs={['write', 'preview']}
            autoFocus
        />
    )
}
