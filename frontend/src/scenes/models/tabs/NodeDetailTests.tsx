import { useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { DataWarehouseTab } from 'scenes/data-warehouse/dataWarehouseSceneLogic'
import { materializationJobsLogic } from 'scenes/data-warehouse/saved_queries/materializationJobsLogic'
import { urls } from 'scenes/urls'

import { dataQualityChecksLogic } from 'products/data_quality/frontend/dataQualityChecksLogic'
import { DataQualityChecksPanel } from 'products/data_quality/frontend/DataQualityChecksPanel'
import { dataQualityGateLogic } from 'products/data_quality/frontend/dataQualityGateLogic'

import { nodeDetailSceneLogic } from '../nodeDetailSceneLogic'

function GateNotice(): JSX.Element | null {
    const { gateConfig, gateReadable } = useValues(dataQualityGateLogic)

    if (!gateReadable || !gateConfig) {
        return null
    }

    return (
        <p className="mb-0 text-secondary text-sm">
            {gateConfig.gate_materialization_on_checks
                ? 'This project blocks materialization on failing error-severity checks.'
                : 'This project materializes this view even when an error-severity check fails.'}{' '}
            <Link to={urls.dataOps(DataWarehouseTab.DATA_QUALITY)} data-attr="node-detail-tests-gate-settings">
                Change this in data quality settings
            </Link>
        </p>
    )
}

export function NodeDetailTests({ id, subjectId }: { id: string; subjectId: string }): JSX.Element {
    const { savedQuery } = useValues(nodeDetailSceneLogic({ id }))
    const { accessDenied } = useValues(dataQualityChecksLogic({ subjectType: 'view', subjectId }))
    const { lastSuccessfulSyncAt } = useValues(materializationJobsLogic({ viewId: subjectId }))

    if (accessDenied) {
        return <p className="mb-0 text-secondary">You don't have access to the tests for this model.</p>
    }

    return (
        <div className="flex flex-col gap-2">
            {savedQuery?.is_materialized && <GateNotice />}
            <DataQualityChecksPanel
                subjectType="view"
                subjectId={subjectId}
                columns={savedQuery?.columns ?? []}
                dataLastSyncedAt={savedQuery?.is_materialized ? lastSuccessfulSyncAt : undefined}
                hideTitle
            />
        </div>
    )
}
