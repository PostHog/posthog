import { useValues } from 'kea'

import { materializationJobsLogic } from 'scenes/data-warehouse/saved_queries/materializationJobsLogic'

import { DataWarehouseSavedQuery } from '~/types'

import { DataQualityChecksPanel } from 'products/data_quality/frontend/DataQualityChecksPanel'

interface ViewDataQualityChecksProps {
    view: DataWarehouseSavedQuery
}

export function ViewDataQualityChecks({ view }: ViewDataQualityChecksProps): JSX.Element {
    // Read the sync time from the run history rather than the view's `last_run_at`, which advances
    // on failed, cancelled and quality-blocked runs too. Those leave the previous version serving,
    // so they must not be named as the sync the checks tested.
    const { lastSuccessfulSyncAt } = useValues(materializationJobsLogic({ viewId: view.id }))

    return (
        <DataQualityChecksPanel
            subjectType="view"
            subjectId={view.id}
            columns={view.columns ?? []}
            dataLastSyncedAt={view.is_materialized ? lastSuccessfulSyncAt : undefined}
        />
    )
}
