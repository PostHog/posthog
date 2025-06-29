import { LemonBanner, LemonButton, LemonModal } from '@posthog/lemon-ui'

import {
    ExperimentFunnelsQuery,
    ExperimentMetric,
    ExperimentTrendsQuery,
    NodeKind,
} from '~/queries/schema/schema-general'
import {
    ExploreAsInsightButton,
    ResultsBreakdown,
    ResultsBreakdownSkeleton,
    ResultsInsightInfoBanner,
    ResultsQuery,
} from '~/scenes/experiments/components/ResultsBreakdown'
import { LegacyExploreButton, LegacyResultsQuery } from '~/scenes/experiments/ExperimentView/components'
import { SignificanceText, WinningVariantText } from '~/scenes/experiments/ExperimentView/Overview'
import { SummaryTable } from '~/scenes/experiments/ExperimentView/SummaryTable'
import type { Experiment, ExperimentIdType } from '~/types'

interface ChartModalProps {
    isOpen: boolean
    onClose: () => void
    metric: ExperimentMetric | ExperimentTrendsQuery | ExperimentFunnelsQuery
    metricIndex: number
    isSecondary: boolean
    result: any
    experimentId: ExperimentIdType
    experiment: Experiment
}

export function ChartModal({
    isOpen,
    onClose,
    metric,
    metricIndex,
    isSecondary,
    result,
    experimentId,
    experiment,
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
            {isLegacyResult ? (
                <>
                    <div className="flex justify-end">
                        <LegacyExploreButton result={result} />
                    </div>
                    <LemonBanner type={result?.significant ? 'success' : 'info'} className="mb-4">
                        <div className="items-center inline-flex flex-wrap">
                            <WinningVariantText result={result} experimentId={experimentId} />
                            <SignificanceText metricIndex={metricIndex} isSecondary={isSecondary} />
                        </div>
                    </LemonBanner>
                    <SummaryTable metric={metric} metricIndex={metricIndex} isSecondary={isSecondary} />
                    <LegacyResultsQuery result={result} showTable={true} />
                </>
            ) : (
                <ResultsBreakdown
                    result={result}
                    experiment={experiment}
                    metricIndex={metricIndex}
                    isPrimary={!isSecondary}
                >
                    {({ query, breakdownResults, breakdownResultsLoading, exposureDifference }) => (
                        <>
                            {query && (
                                <div className="flex justify-end">
                                    <ExploreAsInsightButton query={query} />
                                </div>
                            )}
                            <LemonBanner type={result?.significant ? 'success' : 'info'} className="mb-4">
                                <div className="items-center inline-flex flex-wrap">
                                    <WinningVariantText result={result} experimentId={experimentId} />
                                    <SignificanceText metricIndex={metricIndex} isSecondary={isSecondary} />
                                </div>
                            </LemonBanner>
                            <SummaryTable metric={metric} metricIndex={metricIndex} isSecondary={isSecondary} />
                            {breakdownResultsLoading && <ResultsBreakdownSkeleton />}
                            {query && breakdownResults && (
                                <>
                                    <ResultsInsightInfoBanner exposureDifference={exposureDifference} />
                                    <ResultsQuery query={query} breakdownResults={breakdownResults} />
                                </>
                            )}
                        </>
                    )}
                </ResultsBreakdown>
            )}
        </LemonModal>
    )
}
