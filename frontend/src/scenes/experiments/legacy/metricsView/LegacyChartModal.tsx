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
import type { Experiment } from '~/types'

import { LegacyExploreButton } from '../components/LegacyExploreButton'
import { LegacyResultsQuery } from '../components/LegacyResultsQuery'
import { LegacySummaryTable } from '../components/LegacySummaryTable'
import { LegacyWinningVariantText, LegacySignificanceText } from './LegacyOverview'

interface LegacyChartModalProps {
    isOpen: boolean
    onClose: () => void
    metric: ExperimentMetric | ExperimentTrendsQuery | ExperimentFunnelsQuery
    displayOrder: number
    isSecondary: boolean
    result: any
    experiment: Experiment
}

/**
 * @deprecated
 * This component supports legacy experiment metrics (ExperimentTrendsQuery/ExperimentFunnelsQuery).
 * Frozen copy for legacy experiments - do not modify.
 */
export function LegacyChartModal({
    isOpen,
    onClose,
    metric,
    displayOrder,
    isSecondary,
    result,
    experiment,
}: LegacyChartModalProps): JSX.Element {
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
                            <LegacyWinningVariantText result={result} />
                            <LegacySignificanceText metricUuid={metric.uuid || ''} isSecondary={isSecondary} />
                        </div>
                    </LemonBanner>
                    <LegacySummaryTable metric={metric} displayOrder={displayOrder} isSecondary={isSecondary} />
                    <LegacyResultsQuery result={result} showTable={true} />
                </>
            ) : (
                <ResultsBreakdown
                    result={result}
                    experiment={experiment}
                    metricUuid={metric.uuid || ''}
                    isPrimary={!isSecondary}
                >
                    {({
                        query,
                        breakdownResults,
                        breakdownResultsLoading,
                        exposureDifference,
                        breakdownLastRefresh,
                    }) => (
                        <>
                            {query && (
                                <div className="flex justify-end">
                                    <ExploreAsInsightButton query={query} />
                                </div>
                            )}
                            <LemonBanner type={result?.significant ? 'success' : 'info'} className="mb-4">
                                <div className="items-center inline-flex flex-wrap">
                                    <LegacyWinningVariantText result={result} />
                                    <LegacySignificanceText metricUuid={metric.uuid || ''} isSecondary={isSecondary} />
                                </div>
                            </LemonBanner>
                            <LegacySummaryTable metric={metric} displayOrder={displayOrder} isSecondary={isSecondary} />
                            {breakdownResultsLoading && <ResultsBreakdownSkeleton />}
                            {query && breakdownResults && (
                                <>
                                    <ResultsInsightInfoBanner exposureDifference={exposureDifference} />
                                    <ResultsQuery
                                        query={query}
                                        breakdownResults={breakdownResults}
                                        breakdownLastRefresh={breakdownLastRefresh}
                                    />
                                </>
                            )}
                        </>
                    )}
                </ResultsBreakdown>
            )}
        </LemonModal>
    )
}
