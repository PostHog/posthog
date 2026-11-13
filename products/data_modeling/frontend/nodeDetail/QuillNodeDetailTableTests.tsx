import { useActions, useValues } from 'kea'

import { Button, Skeleton, Text } from '@posthog/quill'

import type { DatabaseSchemaField } from '~/queries/schema/schema-general'

import { QuillDataQualityChecksPanel } from 'products/data_quality/frontend/QuillDataQualityChecksPanel'

import { nodeDetailSceneLogic } from './nodeDetailSceneLogic'

export function QuillNodeDetailTableTests({
    id,
    subjectType,
    subjectId,
    columns,
    editable,
}: {
    id: string
    subjectType: 'table' | 'posthog_table'
    subjectId: string
    columns?: DatabaseSchemaField[]
    editable?: boolean
}): JSX.Element {
    const logic = nodeDetailSceneLogic({ id })
    const { tableDetails, tableDetailsAccessDenied, tableDetailsLoading, tableDetailsError } = useValues(logic)
    const { loadTableDetails } = useActions(logic)
    const lastSyncedAt = tableDetails?.schema?.last_synced_at

    if (subjectType === 'table' && tableDetailsLoading && !tableDetails) {
        return <Skeleton className="h-64 w-full" />
    }

    if (subjectType === 'table' && tableDetailsError && !tableDetails) {
        return (
            <div className="flex flex-wrap items-center gap-2">
                <Text size="xs" variant="muted" render={<span />}>
                    {tableDetailsAccessDenied
                        ? "You don't have access to this table's details."
                        : "Couldn't load table details. Try again."}
                </Text>
                {!tableDetailsAccessDenied && (
                    <Button variant="outline" size="sm" onClick={loadTableDetails} loading={tableDetailsLoading}>
                        Retry
                    </Button>
                )}
            </div>
        )
    }

    return (
        <QuillDataQualityChecksPanel
            subjectType={subjectType}
            subjectId={subjectId}
            columns={subjectType === 'posthog_table' ? (columns ?? []) : (tableDetails?.table.columns ?? [])}
            dataLastSyncedAt={typeof lastSyncedAt === 'string' ? lastSyncedAt : lastSyncedAt?.toISOString()}
            newCheckDisabledReason={
                editable === false ? "You don't have permission to add checks for this table." : undefined
            }
            hideTitle
        />
    )
}
