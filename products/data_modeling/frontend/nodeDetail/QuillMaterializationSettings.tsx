import { useActions, useValues } from 'kea'

import { Button, FieldLegend, FieldSet, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { QuillIncrementalConfigOptions } from 'scenes/data-warehouse/editor/QuillIncrementalConfigOptions'
import { dataWarehouseViewsLogic } from 'scenes/data-warehouse/saved_queries/dataWarehouseViewsLogic'
import { materializationJobsLogic } from 'scenes/data-warehouse/saved_queries/materializationJobsLogic'
import { formatWatermark, refreshModeChange } from 'scenes/data-warehouse/saved_queries/materializationJobUtils'
import { QuillSyncFrequencySelect } from 'scenes/data-warehouse/saved_queries/QuillSyncFrequencySelect'
import { SyncFrequencyValue, defaultCadenceWithin } from 'scenes/data-warehouse/saved_queries/SyncFrequencySelect'

import { AccessControlLevel, AccessControlResourceType, DataWarehouseSavedQuery } from '~/types'

const MATERIALIZATION_DOCS_URL = 'https://posthog.com/docs/data-warehouse/views#materializing-and-scheduling-a-view'

function MaterializedSettings({
    savedQuery,
    kind,
    blockedReason,
}: {
    savedQuery: DataWarehouseSavedQuery
    kind: 'view' | 'endpoint'
    blockedReason: string | undefined
}): JSX.Element {
    const jobsLogic = materializationJobsLogic({ viewId: savedQuery.id, kind })
    const { dataModelingJobs, startingMaterialization, incrementalCheck, incrementalDraft, syncFrequencyDraft } =
        useValues(jobsLogic)
    const { setIncrementalDraft, setSyncFrequencyDraft } = useActions(jobsLogic)
    const { updatingDataWarehouseSavedQuery, materializationActionLoading } = useValues(dataWarehouseViewsLogic)
    const runningReason =
        dataModelingJobs?.results?.[0]?.status === 'Running'
            ? 'Materialization is currently running'
            : startingMaterialization
              ? 'Materialization is starting'
              : undefined
    const frequencyReason = runningReason || blockedReason
    const { structuralChange, refreshModeChanged } = refreshModeChange(savedQuery.incremental, incrementalDraft)
    const showIncremental = kind !== 'endpoint' && !!savedQuery.incremental?.enabled

    return (
        <>
            {showIncremental && savedQuery.incremental_state?.last_run_mode === 'incremental' && (
                <Text size="xs" variant="muted" className="m-0">
                    Updating new rows only, up to {formatWatermark(savedQuery.incremental_state?.watermark)}
                </Text>
            )}
            {kind !== 'endpoint' && (
                <QuillSyncFrequencySelect
                    bounds={savedQuery.sync_frequency_bounds}
                    disabledReason={frequencyReason}
                    value={syncFrequencyDraft ?? (savedQuery.sync_frequency as SyncFrequencyValue) ?? 'never'}
                    onChange={setSyncFrequencyDraft}
                    loading={updatingDataWarehouseSavedQuery || materializationActionLoading}
                />
            )}
            {kind !== 'endpoint' && !savedQuery.managed_viewset_kind && incrementalCheck && (
                <FieldSet className="max-w-160" disabled={!!frequencyReason}>
                    <FieldLegend>Refresh mode</FieldLegend>
                    <QuillIncrementalConfigOptions
                        check={incrementalCheck}
                        draft={incrementalDraft}
                        onChange={setIncrementalDraft}
                    />
                    {refreshModeChanged && incrementalDraft.enabled && (
                        <Text size="xs" variant="muted" className="m-0">
                            {structuralChange
                                ? 'Changing these settings rebuilds the whole table on the next run. After that, runs update only new rows.'
                                : 'The new lookback applies from the next run.'}
                        </Text>
                    )}
                </FieldSet>
            )}
        </>
    )
}

function UnmaterializedSettings({
    savedQuery,
    kind,
    blockedReason,
}: {
    savedQuery: DataWarehouseSavedQuery
    kind: 'view' | 'endpoint'
    blockedReason: string | undefined
}): JSX.Element {
    const jobsLogic = materializationJobsLogic({ viewId: savedQuery.id, kind })
    const { initialSyncFrequency, incrementalCheck, incrementalDraft } = useValues(jobsLogic)
    const { setInitialSyncFrequency, setIncrementalDraft } = useActions(jobsLogic)

    return (
        <>
            <Text size="xs" className="m-0">
                Materialized views are a way to pre-compute data in your data warehouse. This allows you to run queries
                faster and more efficiently.{' '}
                <Button
                    variant="link"
                    size="inline"
                    render={<LinkPrimitive to={MATERIALIZATION_DOCS_URL} target="_blank" />}
                    data-attr="materializing-help"
                >
                    Learn more about materialization
                </Button>
            </Text>
            {kind !== 'endpoint' && (
                <QuillSyncFrequencySelect
                    data-attr="initial-sync-frequency"
                    bounds={savedQuery.sync_frequency_bounds}
                    disabledReason={blockedReason}
                    value={defaultCadenceWithin(savedQuery.sync_frequency_bounds, initialSyncFrequency)}
                    onChange={(newValue) => setInitialSyncFrequency(newValue)}
                />
            )}
            {kind !== 'endpoint' && (
                <div className="max-w-160">
                    <QuillIncrementalConfigOptions
                        check={incrementalCheck}
                        draft={incrementalDraft}
                        onChange={setIncrementalDraft}
                    />
                </div>
            )}
        </>
    )
}

export function QuillMaterializationSettings({
    savedQuery,
    kind,
}: {
    savedQuery: DataWarehouseSavedQuery
    kind: 'view' | 'endpoint'
}): JSX.Element {
    const { savingMaterialization } = useValues(materializationJobsLogic({ viewId: savedQuery.id, kind }))
    const { materializationActionLoading } = useValues(dataWarehouseViewsLogic)
    const accessReason =
        getAccessControlDisabledReason(
            AccessControlResourceType.WarehouseObjects,
            AccessControlLevel.Editor,
            savedQuery.user_access_level
        ) ?? undefined
    const actionReason = materializationActionLoading ? 'Updating materialization' : undefined

    return (
        <div className="flex flex-col gap-4">
            {savedQuery.is_materialized ? (
                <MaterializedSettings
                    savedQuery={savedQuery}
                    kind={kind}
                    blockedReason={
                        (savingMaterialization ? 'Saving materialization settings' : undefined) ||
                        accessReason ||
                        actionReason
                    }
                />
            ) : (
                <UnmaterializedSettings
                    savedQuery={savedQuery}
                    kind={kind}
                    blockedReason={accessReason || actionReason}
                />
            )}
        </div>
    )
}
