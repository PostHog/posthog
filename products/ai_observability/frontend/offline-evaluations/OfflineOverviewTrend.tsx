import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import { LemonBanner, LemonButton, LemonCard, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { offlineOverviewTrendLogic, type OfflineOverviewTrendLogicProps } from './offlineOverviewTrendLogic'
import { OfflineScoreTrendChart } from './OfflineScoreTrendChart'
import { formatOfflineScore, getOfflineHistoryCoverage, offlineScoreMetricLabel } from './offlineScoreTrends'

export function OfflineOverviewTrend(props: OfflineOverviewTrendLogicProps & { timezone: string }): JSX.Element {
    const logic = offlineOverviewTrendLogic(props)
    const { trend, trendLoading, trendError } = useValues(logic)
    const { loadOfflineOverviewTrend } = useActions(logic)
    const latest = trend?.page.results[0]?.summary

    return (
        <LemonCard hoverEffect={false} className="min-w-0 flex flex-col gap-3">
            {trendLoading ? (
                <LemonSkeleton className="h-64" />
            ) : trendError ? (
                <LemonBanner type="error" action={{ children: 'Retry', onClick: loadOfflineOverviewTrend }}>
                    This score could not be loaded. Check your access or choose another score.
                </LemonBanner>
            ) : trend ? (
                <>
                    <div className="flex flex-wrap items-center justify-between gap-2">
                        <h3 className="mb-0 truncate">{trend.definition.name}</h3>
                        <LemonTag type="muted">{trend.definition.kind}</LemonTag>
                    </div>
                    {latest && (
                        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                            <strong>{formatOfflineScore(latest)}</strong>
                            <span className="text-muted text-xs">{`${offlineScoreMetricLabel(latest.scorer)} · v${latest.scorer.version} · ${latest.status_counts.ok} successful results`}</span>
                        </div>
                    )}
                    {trend.page.results.length ? (
                        <OfflineScoreTrendChart
                            heightClassName="h-40"
                            timezone={props.timezone}
                            periods={[
                                {
                                    key: 'overview',
                                    label: 'Experiments',
                                    points: trend.page.results,
                                    dateFrom: props.dateFrom,
                                    dateTo: props.dateTo,
                                },
                            ]}
                            onPointClick={(point) =>
                                router.actions.push(
                                    combineUrl(urls.aiObservabilityOfflineEvaluationExperiment(point.experiment.id), {
                                        scorer_version_id: point.summary.scorer.id,
                                    }).url
                                )
                            }
                        />
                    ) : (
                        <p className="text-muted my-4">No experiments with this score match these filters.</p>
                    )}
                    <p className="text-xs text-muted mb-0">{getOfflineHistoryCoverage(trend.page, props.timezone)}</p>
                    <LemonButton
                        size="xsmall"
                        type="tertiary"
                        className="self-start"
                        to={
                            combineUrl(urls.aiObservabilityOfflineScorerHistory(props.scorerId), {
                                ...props.filters,
                                date_from: props.dateFrom || 'all',
                                date_to: props.dateTo,
                            }).url
                        }
                        data-attr="offline-score-view-history"
                    >
                        View history
                    </LemonButton>
                </>
            ) : null}
        </LemonCard>
    )
}
