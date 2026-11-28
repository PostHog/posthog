import { useValues } from 'kea'

import {
    Button,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyMedia,
    EmptyTitle,
    Spinner,
} from '@posthog/quill'

import type { OutputStateViews } from './outputStateViews'
import { QuillOutputEmptyState } from './QuillOutputEmptyState'
import { QuillOutputErrorState } from './QuillOutputErrorState'
import { sqlEditorLogic } from './sqlEditorLogic'

/** The results pane's empty, no-rows, error and chart-loading states in the quill workspace. */
export const QUILL_OUTPUT_STATE_VIEWS: OutputStateViews = {
    Empty: function QuillEmpty({ kind }) {
        const { singleStatement } = useValues(sqlEditorLogic)
        return <QuillOutputEmptyState kind={kind} singleStatement={!!singleStatement} />
    },
    NoRows: function QuillNoRows() {
        return (
            <Empty className="flex-1" data-attr="sql-editor-output-pane-no-rows-state">
                <EmptyHeader>
                    <EmptyTitle>No rows</EmptyTitle>
                    <EmptyDescription>The query ran and returned no rows.</EmptyDescription>
                </EmptyHeader>
            </Empty>
        )
    },
    Error: function QuillError({ error, validationError, cancelled, showQueryScan }) {
        return (
            <QuillOutputErrorState
                error={validationError || error}
                cancelled={cancelled}
                showQueryScan={showQueryScan}
            />
        )
    },
    ChoosingChart: function QuillChoosingChart({ onSkip }) {
        return (
            <Empty className="flex-1" data-attr="sql-editor-chart-loading" aria-busy="true">
                <EmptyHeader>
                    <EmptyMedia variant="icon">
                        <Spinner />
                    </EmptyMedia>
                    <EmptyTitle role="status">Choosing a chart…</EmptyTitle>
                </EmptyHeader>
                <EmptyContent>
                    <Button variant="outline" onClick={onSkip}>
                        Show results now
                    </Button>
                </EmptyContent>
            </Empty>
        )
    },
}
