import { useValues } from 'kea'

import { Button } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { materializationJobsLogic } from 'scenes/data-warehouse/saved_queries/materializationJobsLogic'
import { urls } from 'scenes/urls'

import { dataQualityGateLogic } from 'products/data_quality/frontend/dataQualityGateLogic'
import { QuillCheckCallout } from 'products/data_quality/frontend/QuillCheckCallout'
import { QuillDataQualityChecksPanel } from 'products/data_quality/frontend/QuillDataQualityChecksPanel'

import { nodeDetailSceneLogic } from './nodeDetailSceneLogic'

function GateNotice(): JSX.Element | null {
    const { gateConfig, gateReadable } = useValues(dataQualityGateLogic)

    if (!gateReadable || !gateConfig) {
        return null
    }

    return (
        <QuillCheckCallout tone="info">
            {gateConfig.gate_materialization_on_checks
                ? 'This project blocks materialization on failing error-severity checks.'
                : 'This project materializes this view even when an error-severity check fails.'}{' '}
            <Button
                variant="link"
                size="inline"
                render={<LinkPrimitive to={urls.settings('environment-data-quality')} />}
                data-attr="node-detail-tests-gate-settings"
            >
                Change this in data quality settings
            </Button>
        </QuillCheckCallout>
    )
}

export function QuillNodeDetailViewTests({ id, subjectId }: { id: string; subjectId: string }): JSX.Element {
    const { savedQuery } = useValues(nodeDetailSceneLogic({ id }))
    const { lastSuccessfulSyncAt } = useValues(materializationJobsLogic({ viewId: subjectId }))

    return (
        <QuillDataQualityChecksPanel
            subjectType="view"
            subjectId={subjectId}
            columns={savedQuery?.columns ?? []}
            dataLastSyncedAt={savedQuery?.is_materialized ? lastSuccessfulSyncAt : undefined}
            hideTitle
            notice={savedQuery?.is_materialized ? <GateNotice /> : undefined}
        />
    )
}
