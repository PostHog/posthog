import { useActions, useValues } from 'kea'

import { IconChevronDown, IconPlay } from '@posthog/icons'
import { LemonButton, LemonMenuItems, LemonMenuOverlay } from '@posthog/lemon-ui'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { notebookSettingsLogic } from '../../Notebook/notebookSettingsLogic'
import { isKernelUiEnabled } from '../../utils'
import { NotebookRunMode, buildRunMenuItems } from './runMenuItems'

export type HogqlSqlRunMode = NotebookRunMode

type HogqlSqlRunMenuProps = {
    isFresh: boolean
    isStale: boolean
    loading: boolean
    queued: boolean
    disabledReason?: string
    onRun: (mode: HogqlSqlRunMode) => void
}

export const HogqlSqlRunMenu = ({
    isFresh,
    isStale,
    loading,
    queued,
    disabledReason,
    onRun,
}: HogqlSqlRunMenuProps): JSX.Element => {
    const { featureFlags } = useValues(featureFlagLogic)
    const { showKernelInfo } = useValues(notebookSettingsLogic)
    const { setShowKernelInfo } = useActions(notebookSettingsLogic)
    const hogqlRunIconClass = isFresh ? 'text-success' : isStale ? 'text-danger' : undefined
    const hogqlRunTooltip = `Run SQL (HogQL) query.${queued ? ' Queued.' : isStale ? ' Stale.' : ''}`

    const hogqlRunMenuItems: LemonMenuItems = [...buildRunMenuItems(onRun)]

    if (isKernelUiEnabled(featureFlags)) {
        hogqlRunMenuItems.push({
            label: 'Toggle kernel info',
            onClick: () => setShowKernelInfo(!showKernelInfo),
        })
    }

    return (
        <LemonButton
            onClick={() => onRun('auto')}
            size="small"
            icon={<IconPlay className={hogqlRunIconClass} />}
            loading={loading || queued}
            disabledReason={disabledReason}
            tooltip={hogqlRunTooltip}
            sideAction={{
                icon: <IconChevronDown />,
                dropdown: {
                    placement: 'bottom-end',
                    overlay: <LemonMenuOverlay items={hogqlRunMenuItems} />,
                },
                divider: false,
                'aria-label': 'Open run options',
                disabledReason: disabledReason,
            }}
        />
    )
}
