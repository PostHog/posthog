import { LemonTag } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { BatchExportConfiguration, BatchExportRun } from '~/types'

export function BatchExportTag({ batchExportConfig }: { batchExportConfig: BatchExportConfiguration }): JSX.Element {
    return (
        <LemonTag type={batchExportConfig.paused ? 'default' : 'primary'} className="uppercase">
            {batchExportConfig.paused ? 'Paused' : 'Active'}
        </LemonTag>
    )
}

export function BatchExportRunIcon({ batchExportRun }: { batchExportRun: BatchExportRun }): JSX.Element {
    let color = 'default'
    let runCount = 1

    switch (batchExportRun.status) {
        case 'Completed':
            color = 'success'
            break
        case 'ContinuedAsNew':
        case 'Running':
        case 'Starting':
            color = 'primary'
            break
        case 'Cancelled':
        case 'Terminated':
        case 'TimedOut':
            color = 'warning'
            break
        case 'Failed':
            color = 'danger'
            break
    }

    return (
        <Tooltip
            title={
                <>
                    Run status: {batchExportRun.status}
                    <br />
                    Attempts: {runCount}
                </>
            }
        >
            <span
                className={clsx(
                    `h-6 w-6 border-2 flex items-center justify-center rounded-full font-semibold text-sm text-muted border-${color}`
                )}
            >
                {runCount}
            </span>
        </Tooltip>
    )
}

export function BatchExportRunStatus({ batchExportRun }: { batchExportRun: BatchExportRun }): JSX.Element {
    let status = batchExportRun.status

    if (batchExportRun.status === 'Running') {
        return (
            <LemonTag type="primary" className="uppercase">
                Running
            </LemonTag>
        )
    } else if (batchExportRun.status === 'Completed') {
        return (
            <LemonTag type="success" className="uppercase">
                Completed
            </LemonTag>
        )
    } else if (batchExportRun.status === 'Starting') {
        return (
            <LemonTag type="default" className="uppercase">
                Starting
            </LemonTag>
        )
    } else {
        return (
            <LemonTag type="danger" className="uppercase">
                Error
            </LemonTag>
        )
    }
}
