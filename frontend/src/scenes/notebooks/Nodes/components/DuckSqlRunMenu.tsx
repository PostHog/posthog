import { useActions, useValues } from 'kea'

import { IconChevronDown, IconPlay } from '@posthog/icons'
import { LemonButton, LemonMenuItems, LemonMenuOverlay } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { notebookSettingsLogic } from '../../Notebook/notebookSettingsLogic'
import { NotebookRunMode, buildRunMenuItems } from './runMenuItems'

export type DuckSqlRunMode = NotebookRunMode

type DuckSqlRunMenuProps = {
    isFresh: boolean
    isStale: boolean
    loading: boolean
    queued: boolean
    disabledReason?: string
    onRun: (mode: DuckSqlRunMode) => void
}

export const DuckSqlRunMenu = ({
    isFresh,
    isStale,
    loading,
    queued,
    disabledReason,
    onRun,
}: DuckSqlRunMenuProps): JSX.Element => {
    const { featureFlags } = useValues(featureFlagLogic)
    const { showKernelInfo } = useValues(notebookSettingsLogic)
    const { setShowKernelInfo } = useActions(notebookSettingsLogic)
    const duckSqlRunIconClass = isFresh ? 'text-success' : isStale ? 'text-danger' : undefined
    const duckSqlRunTooltip = `Run SQL (duckdb) query.${queued ? ' Queued.' : isStale ? ' Stale.' : ''}`

    const duckSqlRunMenuItems: LemonMenuItems = [...buildRunMenuItems(onRun)]

    if (featureFlags[FEATURE_FLAGS.NOTEBOOK_PYTHON]) {
        duckSqlRunMenuItems.push({
            label: 'Toggle kernel info',
            onClick: () => setShowKernelInfo(!showKernelInfo),
        })
    }

    return (
        <LemonButton
            onClick={() => onRun('auto')}
            size="small"
            icon={<IconPlay className={duckSqlRunIconClass} />}
            loading={loading || queued}
            disabledReason={disabledReason}
            tooltip={duckSqlRunTooltip}
            sideAction={{
                icon: <IconChevronDown />,
                dropdown: {
                    placement: 'bottom-end',
                    overlay: <LemonMenuOverlay items={duckSqlRunMenuItems} />,
                },
                divider: false,
                'aria-label': 'Open run options',
                disabledReason: disabledReason,
            }}
        />
    )
}
