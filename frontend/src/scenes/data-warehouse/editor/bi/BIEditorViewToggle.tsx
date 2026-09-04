import type { ReactNode } from 'react'

import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'

import { BIEditorView, type BIQueryBuildResult } from './biEditorTypes'
import { shouldConfirmEnteringBIEditor } from './biEditorViewUtils'

interface BIEditorViewToggleProps {
    editorView: BIEditorView
    queryInput: string | null | undefined
    generatedQuery: BIQueryBuildResult | null
    setEditorView: (editorView: BIEditorView) => void
}

export function BIEditorViewToggle({
    editorView,
    queryInput,
    generatedQuery,
    setEditorView,
}: BIEditorViewToggleProps): ReactNode {
    const handleEditorViewChange = (nextEditorView: BIEditorView): void => {
        if (!shouldConfirmEnteringBIEditor(nextEditorView, queryInput, generatedQuery)) {
            setEditorView(nextEditorView)
            return
        }

        LemonDialog.open({
            title: 'Open Builder?',
            description: generatedQuery
                ? 'Builder cannot convert the current SQL. Continuing replaces it with your previous Builder setup.'
                : 'Builder cannot convert the current SQL. Changes you make in Builder will replace it.',
            primaryButton: {
                children: 'Open Builder',
                onClick: () => setEditorView(nextEditorView),
            },
            secondaryButton: {
                children: 'Cancel',
                type: 'tertiary',
            },
        })
    }

    return (
        <LemonSegmentedButton
            value={editorView}
            onChange={handleEditorViewChange}
            options={[
                { value: BIEditorView.SQL, label: 'SQL' },
                {
                    value: BIEditorView.BI,
                    label: 'Builder',
                    tooltip: 'Build a query from fields without writing SQL',
                    'data-attr': 'sql-editor-builder-mode',
                },
            ]}
            size="small"
        />
    )
}
