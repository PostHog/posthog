import { Button } from '@posthog/quill'

import { METRIC_MARKDOWN_MAX_LENGTH } from '../common'
import { MetricMarkdownEditorField } from './MetricMarkdownEditorField'

export interface QuillMarkdownDefinitionEditorProps {
    draftMarkdown: string
    saving: boolean
    onDraftMarkdown: (value: string) => void
    onSave: (markdown: string) => void
    onCancel: () => void
}

function saveDisabledReason(draftMarkdown: string): string | undefined {
    if (!draftMarkdown.trim()) {
        return 'Add the markdown definition'
    }
    if (draftMarkdown.length > METRIC_MARKDOWN_MAX_LENGTH) {
        return `Keep the definition under ${METRIC_MARKDOWN_MAX_LENGTH} characters`
    }
    return undefined
}

export function QuillMarkdownDefinitionEditor({
    draftMarkdown,
    saving,
    onDraftMarkdown,
    onSave,
    onCancel,
}: QuillMarkdownDefinitionEditorProps): JSX.Element {
    return (
        <>
            <MetricMarkdownEditorField value={draftMarkdown} onChange={onDraftMarkdown} />
            <div className="flex flex-wrap gap-2">
                <Button
                    variant="primary"
                    loading={saving}
                    disabledReason={saveDisabledReason(draftMarkdown)}
                    onClick={() => onSave(draftMarkdown)}
                >
                    Save
                </Button>
                <Button variant="outline" onClick={onCancel}>
                    Cancel
                </Button>
            </div>
        </>
    )
}
