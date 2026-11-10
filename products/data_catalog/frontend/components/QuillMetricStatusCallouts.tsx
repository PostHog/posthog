import { Button } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { InsightShortId } from '~/types'

import type { DataCatalogMetricApi } from '../generated/api.schemas'
import { WORKING_REASON } from '../metricSceneActions'
import { QuillMetricCallout } from './QuillMetricCallout'

export interface QuillMetricStatusCalloutsProps {
    metric: DataCatalogMetricApi
    mutating: boolean
    onApprove: () => void
    onRefreshFromInsight: () => void
}

export function QuillMetricStatusCallouts({
    metric,
    mutating,
    onApprove,
    onRefreshFromInsight,
}: QuillMetricStatusCalloutsProps): JSX.Element | null {
    const sourceShortId = metric.source_insight_short_id

    if (metric.is_drifted) {
        return (
            <QuillMetricCallout
                tone="warning"
                actions={
                    sourceShortId ? (
                        <>
                            <Button variant="outline" onClick={onRefreshFromInsight}>
                                Refresh from insight
                            </Button>
                            <Button
                                variant="outline"
                                render={<LinkPrimitive to={urls.insightView(sourceShortId as InsightShortId)} />}
                            >
                                View source insight
                            </Button>
                        </>
                    ) : undefined
                }
            >
                This metric has drifted from its source insight, so it cannot be approved. Refresh it from the insight
                to pick up the current query.
            </QuillMetricCallout>
        )
    }

    if (metric.status === 'approved') {
        return null
    }

    return (
        <QuillMetricCallout
            tone="info"
            actions={
                <Button
                    variant="primary"
                    onClick={onApprove}
                    disabledReason={mutating ? WORKING_REASON : undefined}
                    data-attr="data-catalog-metric-approve"
                >
                    Approve metric
                </Button>
            }
        >
            This metric is proposed. Approve it once the definition looks right.
        </QuillMetricCallout>
    )
}
