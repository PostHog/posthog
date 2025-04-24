import { LemonBanner, LemonButton, LemonModal } from '@posthog/lemon-ui'

import {
    ExperimentFunnelsQuery,
    ExperimentMetric,
    ExperimentTrendsQuery,
    NodeKind,
} from '~/queries/schema/schema-general'
import { ExperimentIdType } from '~/types'

import { ExploreButton, ResultsQuery } from '../ExperimentView/components'
import { SignificanceText, WinningVariantText } from '../ExperimentView/Overview'
import { SummaryTable } from '../ExperimentView/SummaryTable'

interface ChartModalProps {
    isOpen: boolean
    onClose: () => void
    metric: ExperimentMetric | ExperimentTrendsQuery | ExperimentFunnelsQuery
    metricIndex: number
    isSecondary: boolean
    result: any
    experimentId: ExperimentIdType
}

export function ChartModal({
    isOpen,
    onClose,
    metric,
    metricIndex,
    isSecondary,
    result,
    experimentId,
}: ChartModalProps): JSX.Element {
    const isLegacyResult =
        result && (result.kind === NodeKind.ExperimentTrendsQuery || result.kind === NodeKind.ExperimentFunnelsQuery)
    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            width={1200}
            title={`Metric results: ${metric.name || 'Untitled metric'}`}
            footer={
                <LemonButton type="secondary" onClick={onClose}>
                    Close
                </LemonButton>
            }
        >
            {/* Only show explore button if the metric is a trends or funnels query */}
            {isLegacyResult && (
                <div className="flex justify-end">
                    <ExploreButton result={result} />
                </div>
            )}
            <LemonBanner type={result?.significant ? 'success' : 'info'} className="mb-4">
                <div className="items-center inline-flex flex-wrap">
                    <WinningVariantText result={result} experimentId={experimentId} />
                    <SignificanceText metricIndex={metricIndex} isSecondary={isSecondary} />
                </div>
            </LemonBanner>
            <SummaryTable metric={metric} metricIndex={metricIndex} isSecondary={isSecondary} />
            {/* Only show results query if the metric is a trends or funnels query */}
            {isLegacyResult && <ResultsQuery result={result} showTable={true} />}
        </LemonModal>
    )
}
