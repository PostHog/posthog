import { LemonTag } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { BatchExportConfiguration, BatchExportRun } from '~/types'

import './batch-exports.scss'

export function BatchExportTag({ batchExportConfig }: { batchExportConfig: BatchExportConfiguration }): JSX.Element {
    return (
        <LemonTag type={batchExportConfig.paused ? 'default' : 'primary'} className="uppercase">
            {batchExportConfig.paused ? 'Paused' : 'Active'}
        </LemonTag>
    )
}

export const colorForStatus = (
    status: BatchExportRun['status']
): 'success' | 'primary' | 'warning' | 'danger' | 'default' => {
    switch (status) {
        case 'Completed':
            return 'success'
        case 'ContinuedAsNew':
        case 'Running':
        case 'Starting':
            return 'primary'
        case 'Cancelled':
        case 'Terminated':
        case 'TimedOut':
            return 'warning'
        case 'Failed':
            return 'danger'
        default:
            return 'default'
    }
}

export function BatchExportRunIcon({
    runs,
    showLabel = false,
}: {
    runs: BatchExportRun[]
    showLabel?: boolean
}): JSX.Element {
    // We assume these are pre-sorted
    const latestRun = runs[0]

    const color = colorForStatus(latestRun.status)

    return (
        <Tooltip
            title={
                <>
                    Run status: {latestRun.status}
                    {runs.length > 1 && (
                        <>
                            <br />
                            Attempts: {runs.length}
                        </>
                    )}
                </>
            }
        >
            <span
                className={clsx(
                    `h-6 p-2 border-2 flex items-center justify-center rounded-full font-semibold text-xs border-${color} text-${color}-dark select-none`,
                    color === 'primary' && 'BatchExportRunIcon--pulse',
                    showLabel ? '' : 'w-6'
                )}
            >
                {showLabel ? <span className="text-center">{latestRun.status}</span> : runs.length}
            </span>
        </Tooltip>
    )
}
