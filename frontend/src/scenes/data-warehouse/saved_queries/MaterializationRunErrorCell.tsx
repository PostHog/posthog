import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { DataModelingJobStatus } from '~/types'

interface MaterializationRunErrorCellProps {
    error: string | null
    status: DataModelingJobStatus
}

function openRunErrorDialog(error: string, status: DataModelingJobStatus): void {
    LemonDialog.open({
        title: status === 'Completed' ? 'Run warning' : 'Run error',
        maxWidth: '40rem',
        content: (
            <pre className="whitespace-pre-wrap break-words text-xs font-mono max-h-[60vh] overflow-y-auto m-0">
                {error}
            </pre>
        ),
        tertiaryButton: {
            children: 'Copy',
            preventClosing: true,
            onClick: () => void copyToClipboard(error, 'error'),
        },
        primaryButton: { children: 'Close' },
    })
}

export function MaterializationRunErrorCell({ error, status }: MaterializationRunErrorCellProps): JSX.Element | null {
    if (!error) {
        return null
    }
    const firstLine = error.split('\n')[0]
    const textColor = status === 'Completed' ? 'text-secondary' : 'text-danger'
    return (
        <div className="flex items-center gap-1 max-w-60" data-attr="materialization-run-error">
            <Tooltip title={error} interactive>
                <span className={`truncate min-w-0 ${textColor}`}>{firstLine}</span>
            </Tooltip>
            <LemonButton
                size="xsmall"
                type="tertiary"
                onClick={() => openRunErrorDialog(error, status)}
                data-attr="materialization-run-error-view"
            >
                View
            </LemonButton>
        </div>
    )
}
