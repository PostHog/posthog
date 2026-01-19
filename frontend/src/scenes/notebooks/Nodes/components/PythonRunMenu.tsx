import { useActions, useValues } from 'kea'

import { IconChevronDown, IconPlay } from '@posthog/icons'
import { LemonButton, LemonMenuItems, LemonMenuOverlay } from '@posthog/lemon-ui'

import { notebookSettingsLogic } from '../../Notebook/notebookSettingsLogic'
import { NotebookRunMode, buildRunMenuItems } from './runMenuItems'

export type PythonRunMode = NotebookRunMode

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
        ...buildRunMenuItems(onRun),
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
