import { useValues } from 'kea'

import { LemonBanner, Spinner } from '@posthog/lemon-ui'

import { dataQualityChecksLogic } from 'products/data_quality/frontend/dataQualityChecksLogic'
import { DataQualityChecksPanel } from 'products/data_quality/frontend/DataQualityChecksPanel'

import { dataCatalogMetricSceneLogic } from '../dataCatalogMetricSceneLogic'

const NEW_CHECK_NEEDS_SQL_REASON = 'Tests are available for SQL metrics only'

export function MetricTestsTab(): JSX.Element | null {
    const { metric, supportsMetricChecks } = useValues(dataCatalogMetricSceneLogic)

    if (!metric) {
        return null
    }
    if (!supportsMetricChecks) {
        return <UnsupportedDefinitionTests subjectId={metric.id} />
    }

    return <DataQualityChecksPanel subjectType="metric" subjectId={metric.id} columns={[]} hideTitle />
}

function UnsupportedDefinitionTests({ subjectId }: { subjectId: string }): JSX.Element {
    const { checks, checksLoaded, checksLoadError } = useValues(
        dataQualityChecksLogic({ subjectType: 'metric', subjectId })
    )

    if (!checksLoaded && !checksLoadError) {
        return <Spinner />
    }
    if (checks.length === 0) {
        return (
            <LemonBanner type="info">
                Tests are available for SQL metrics only. Save a HogQL query as this metric's definition to add checks.
            </LemonBanner>
        )
    }

    return (
        <>
            <LemonBanner type="warning">
                This metric's definition is not SQL, so these checks fail on every run. Turn them off or delete them, or
                save a HogQL query as the definition.
            </LemonBanner>
            <DataQualityChecksPanel
                subjectType="metric"
                subjectId={subjectId}
                columns={[]}
                hideTitle
                newCheckDisabledReason={NEW_CHECK_NEEDS_SQL_REASON}
            />
        </>
    )
}
