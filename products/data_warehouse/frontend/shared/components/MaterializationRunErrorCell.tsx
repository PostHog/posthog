import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'

import { DataModelingJobStatus } from '~/types'

interface MaterializationRunErrorCellProps {
    error: string | null
    status: DataModelingJobStatus
}

interface RunErrorPresentation {
    dialogTitle: string
    copyNoun: string
    textClass: string
}

const PRESENTATION_BY_STATUS: Record<DataModelingJobStatus, RunErrorPresentation> = {
    Failed: { dialogTitle: 'Run error', copyNoun: 'error', textClass: 'text-danger' },
    Completed: { dialogTitle: 'Run warning', copyNoun: 'warning', textClass: 'text-secondary' },
    Skipped: { dialogTitle: 'Skip reason', copyNoun: 'skip reason', textClass: 'text-secondary' },
    Cancelled: { dialogTitle: 'Cancellation reason', copyNoun: 'cancellation reason', textClass: 'text-secondary' },
    Running: { dialogTitle: 'Run message', copyNoun: 'message', textClass: 'text-secondary' },
}

const LINES_SHOWN_BEFORE_EXPANSION = 20

function openRunErrorDialog(error: string, presentation: RunErrorPresentation): void {
    LemonDialog.open({
        title: presentation.dialogTitle,
        maxWidth: '40rem',
        content: (
            <CodeSnippet
                language={Language.Text}
                wrap
                compact
                thing={presentation.copyNoun}
                maxLinesWithoutExpansion={LINES_SHOWN_BEFORE_EXPANSION}
            >
                {error}
            </CodeSnippet>
        ),
        primaryButton: { children: 'Close' },
    })
}

export function MaterializationRunErrorCell({ error, status }: MaterializationRunErrorCellProps): JSX.Element | null {
    if (!error) {
        return null
    }
    const presentation = PRESENTATION_BY_STATUS[status]
    const firstLine = error.split('\n')[0]
    return (
        <div className="flex items-center gap-1 max-w-60" data-attr="materialization-run-error">
            <span className={`truncate min-w-0 ${presentation.textClass}`}>{firstLine}</span>
            <LemonButton
                size="xsmall"
                type="tertiary"
                onClick={() => openRunErrorDialog(error, presentation)}
                data-attr="materialization-run-error-view"
            >
                View
            </LemonButton>
        </div>
    )
}
