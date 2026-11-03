import { useValues } from 'kea'

import { Spinner } from '@posthog/quill'

import { dataQualityChecksLogic } from 'products/data_quality/frontend/dataQualityChecksLogic'
import { QuillMetricChecksPanel } from 'products/data_quality/frontend/QuillMetricChecksPanel'

import { QuillMetricCallout } from '../components/QuillMetricCallout'
import { dataCatalogMetricSceneLogic } from '../dataCatalogMetricSceneLogic'
import { NEW_CHECK_NEEDS_SQL_REASON } from './MetricTestsTab'

function QuillUnsupportedDefinitionTests({
    metricId,
    metricName,
}: {
    metricId: string
    metricName: string
}): JSX.Element {
    const { checks, checksLoaded, checksLoadError } = useValues(
        dataQualityChecksLogic({ subjectType: 'metric', subjectId: metricId })
    )

    if (!checksLoaded && !checksLoadError) {
        return <Spinner />
    }
    if (checks.length === 0) {
        return (
            <QuillMetricCallout tone="info">
                Tests are available for SQL metrics only. Save a HogQL query as this metric's definition to add checks.
            </QuillMetricCallout>
        )
    }

    return (
        <>
            <QuillMetricCallout tone="warning">
                This metric's definition is not SQL, so these checks fail on every run. Turn them off or delete them, or
                save a HogQL query as the definition.
            </QuillMetricCallout>
            <QuillMetricChecksPanel
                metricId={metricId}
                metricName={metricName}
                newCheckDisabledReason={NEW_CHECK_NEEDS_SQL_REASON}
            />
        </>
    )
}

export function QuillMetricTestsTab(): JSX.Element | null {
    const { metric, supportsMetricChecks } = useValues(dataCatalogMetricSceneLogic)

    if (!metric) {
        return null
    }
    if (!supportsMetricChecks) {
        return <QuillUnsupportedDefinitionTests metricId={metric.id} metricName={metric.display_name || metric.name} />
    }

    return <QuillMetricChecksPanel metricId={metric.id} metricName={metric.display_name || metric.name} />
}
