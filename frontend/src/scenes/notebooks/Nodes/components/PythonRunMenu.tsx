import { useActions, useValues } from 'kea'

import { IconChevronDown, IconPlay } from '@posthog/icons'
import { LemonButton, LemonMenuItems, LemonMenuOverlay } from '@posthog/lemon-ui'

import { notebookSettingsLogic } from '../../Notebook/notebookSettingsLogic'

export type PythonRunMode = 'auto' | 'cell_upstream' | 'cell' | 'cell_downstream'

type PythonRunMenuProps = {
    isFresh: boolean
    isStale: boolean
    loading: boolean
    queued: boolean
    disabledReason?: string
    onRun: (mode: PythonRunMode) => void
}

export const PythonRunMenu = ({
    isFresh,
    isStale,
    loading,
    queued,
    disabledReason,
    onRun,
}: PythonRunMenuProps): JSX.Element => {
    const { showKernelInfo } = useValues(notebookSettingsLogic)
    const { setShowKernelInfo } = useActions(notebookSettingsLogic)
    const pythonRunIconClass = isFresh ? 'text-success' : isStale ? 'text-danger' : undefined
    const pythonRunTooltip = `Run Python cell.${queued ? ' Queued.' : isStale ? ' Stale.' : ''}`

    const pythonRunMenuItems: LemonMenuItems = [
        {
            label: 'Run (auto)',
            onClick: () => onRun('auto'),
        },
        {
            label: 'Run cell + upstream',
            onClick: () => onRun('cell_upstream'),
        },
        {
            label: 'Run cell',
            onClick: () => onRun('cell'),
        },
        {
            label: 'Run cell + downstream',
            onClick: () => onRun('cell_downstream'),
        },
        {
            label: 'Toggle kernel info',
            onClick: () => setShowKernelInfo(!showKernelInfo),
        },
    ]

    return (
        <LemonButton
            onClick={() => onRun('auto')}
            size="small"
            icon={<IconPlay className={pythonRunIconClass} />}
            loading={loading || queued}
            disabledReason={disabledReason}
            tooltip={pythonRunTooltip}
            sideAction={{
                icon: <IconChevronDown />,
                dropdown: {
                    placement: 'bottom-end',
                    overlay: <LemonMenuOverlay items={pythonRunMenuItems} />,
                },
                divider: false,
                'aria-label': 'Open run options',
                disabledReason: disabledReason,
            }}
        />
    )
}
