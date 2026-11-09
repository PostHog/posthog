import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { BatchExportConfiguration } from '~/types'

import { batchExportRunsLogic } from './batchExportRunsLogic'
import { BatchExportContext } from './types'
import { hasBatchExportEnded, humanizeBatchExportInterval } from './utils'

export function BatchExportRunsEmptyState({
    id,
    context,
    interval,
}: {
    id: string
    context?: BatchExportContext
    interval: BatchExportConfiguration['interval']
}): JSX.Element {
    const { statusFilterActive, batchExportConfig } = useValues(batchExportRunsLogic({ id }))
    const { setStatusFilter, openBackfillModal } = useActions(batchExportRunsLogic({ id }))

    if (statusFilterActive) {
        return (
            <div className="deprecated-space-y-2">
                <div>No runs match this status filter.</div>
                <LemonButton type="secondary" onClick={() => setStatusFilter([])}>
                    Clear filter
                </LemonButton>
            </div>
        )
    }

    return (
        <div className="deprecated-space-y-2">
            <div>
                {context === 'hog_function'
                    ? 'No runs in this time range.'
                    : batchExportConfig && hasBatchExportEnded(batchExportConfig)
                      ? "No runs in this time range. This batch export's end date has passed, so it has no more scheduled runs. Change the end date in the Configuration tab to extend its schedule."
                      : batchExportConfig?.paused
                        ? 'No runs in this time range. This batch export is paused. Enable it in the Configuration tab to resume scheduled runs.'
                        : `No runs in this time range. This batch export runs ${humanizeBatchExportInterval(interval).toLowerCase()}.`}
            </div>
            <LemonButton type="primary" onClick={() => openBackfillModal()}>
                Start backfill
            </LemonButton>
        </div>
    )
}
