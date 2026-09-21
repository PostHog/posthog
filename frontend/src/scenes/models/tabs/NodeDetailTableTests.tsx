import { useActions, useValues } from 'kea'

import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { DataQualityChecksPanel } from 'products/data_quality/frontend/DataQualityChecksPanel'

import { nodeDetailSceneLogic } from '../nodeDetailSceneLogic'

export function NodeDetailTableTests({ id, subjectId }: { id: string; subjectId: string }): JSX.Element {
    const logic = nodeDetailSceneLogic({ id })
    const { tableDetails, tableDetailsAccessDenied, tableDetailsLoading, tableDetailsError } = useValues(logic)
    const { loadTableDetails } = useActions(logic)
    const lastSyncedAt = tableDetails?.schema?.last_synced_at

    if (tableDetailsLoading && !tableDetails) {
        return <LemonSkeleton className="h-64 w-full" />
    }

    if (tableDetailsError && !tableDetails) {
        return (
            <div className="flex flex-wrap items-center gap-2 text-secondary">
                <span>
                    {tableDetailsAccessDenied
                        ? "You don't have access to this table's details."
                        : "Couldn't load table details. Try again."}
                </span>
                {!tableDetailsAccessDenied && (
                    <LemonButton size="xsmall" onClick={loadTableDetails} loading={tableDetailsLoading}>
                        Retry
                    </LemonButton>
                )}
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-4">
            <DataQualityChecksPanel
                subjectType="table"
                subjectId={subjectId}
                columns={tableDetails?.table.columns ?? []}
                dataLastSyncedAt={
                    typeof lastSyncedAt === 'string' ? lastSyncedAt : lastSyncedAt?.toISOString()
                }
                hideTitle
            />
        </div>
    )
}
