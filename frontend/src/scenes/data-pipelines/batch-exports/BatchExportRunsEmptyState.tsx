import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { BatchExportConfiguration } from '~/types'

import { batchExportRunsLogic } from './batchExportRunsLogic'

export function BatchExportRunsEmptyState({
    id,
    interval,
}: {
    id: string
    interval: BatchExportConfiguration['interval']
}): JSX.Element {
    const { statusFilterActive } = useValues(batchExportRunsLogic({ id }))
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
                No runs in this time range. Your exporter runs every <b>{interval}</b>.
            </div>
            <LemonButton type="primary" onClick={() => openBackfillModal()}>
                Start backfill
            </LemonButton>
        </div>
    )
}
