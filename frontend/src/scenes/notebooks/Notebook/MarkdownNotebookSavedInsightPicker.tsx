import { LemonButton } from '@posthog/lemon-ui'

import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { useSummarizeInsight } from 'scenes/insights/summarizeInsight'
import { SavedInsightsTable } from 'scenes/saved-insights/SavedInsightsTable'

export type MarkdownNotebookSavedInsightPickerProps = {
    isOpen: boolean
    title?: string
    onClose: () => void
    onSelect: (shortId: string, title: string) => void
}

export function MarkdownNotebookSavedInsightPicker({
    isOpen,
    title = 'Add insight to notebook',
    onClose,
    onSelect,
}: MarkdownNotebookSavedInsightPickerProps): JSX.Element {
    const summarizeInsight = useSummarizeInsight()

    return (
        <LemonModal
            title={title}
            onClose={onClose}
            isOpen={isOpen}
            footer={
                <LemonButton type="secondary" data-attr="markdown-notebook-saved-insight-cancel" onClick={onClose}>
                    Close
                </LemonButton>
            }
        >
            <SavedInsightsTable
                onToggle={(insight) => onSelect(insight.short_id, insight.name || summarizeInsight(insight.query))}
            />
        </LemonModal>
    )
}
