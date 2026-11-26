import { useActions, useValues, type BuiltLogic } from 'kea'
import { combineUrl, router } from 'kea-router'

import { IconChevronLeft, IconChevronRight } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCard, LemonSkeleton, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { ScorerBadges } from '../scoreDefinitions/ScorerBadges'
import { experimentScoreLabel } from './ExperimentScoreResult'
import { offlineExperimentUrl } from './offlineExperimentPresentation'
import type { offlineExperimentsLogicType } from './offlineExperimentsLogic'
import { offlineOverviewTrendLogic, type OfflineOverviewTrendLogicProps } from './offlineOverviewTrendLogic'
import { OfflineScoreCounts, OfflineSummaryMetrics } from './OfflineScoreSummaryDisplay'
import { OfflineScoreTrendChart } from './OfflineScoreTrendChart'
import { getOfflineHistoryCoverage } from './offlineScoreTrends'

export function OfflineOverviewTrend(
    props: OfflineOverviewTrendLogicProps & {
        timezone: string
        colorOffset?: number
        xDomain?: [number, number]
        overviewLogic?: BuiltLogic<offlineExperimentsLogicType>
    }
): JSX.Element {
    const { overviewLogic, ...trendProps } = props
    const logic = offlineOverviewTrendLogic(trendProps)
    const { trend, trendLoading, trendError, points, versionSummaries, periodSummary } = useValues(logic)
    const { loadOfflineOverviewTrend, selectVersion } = useActions(logic)
    const versionIndex = versionSummaries.findIndex((summary) => summary.scorer.id === periodSummary?.scorer.id)
    const hasPartialHistory = !!trend && trend.page.count > trend.page.results.length
    const isExperimentScore = trend?.definition.scope === 'experiment'
    const showChart = !isExperimentScore || trend?.definition.kind === 'numeric'
    const latestScore = isExperimentScore && showChart ? points[0]?.experiment.experiment_score : null
    const scoredItemCount = periodSummary
        ? periodSummary.pass_count != null && periodSummary.fail_count != null
            ? periodSummary.pass_count + periodSummary.fail_count
            : periodSummary.status_counts.ok
        : 0

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
                    <div className="flex flex-wrap items-center gap-2">
                        <h3 className="mb-0 min-w-0 break-words">
                            <Link
                                to={
                                    combineUrl(urls.aiObservabilityOfflineScorerHistory(props.scorerId), {
                                        ...props.filters,
                                        version: periodSummary?.scorer.id,
                                        date_from: props.dateFrom || 'all',
                                        date_to: props.dateTo,
                                    }).url
                                }
                                data-attr="offline-score-view-history"
                            >
                                {trend.definition.short_name || trend.definition.name}
                            </Link>
                        </h3>
                        <ScorerBadges
                            scorer={{ ...(periodSummary?.scorer ?? trend.definition), scope: trend.definition.scope }}
                        />
                        {periodSummary && (
                            <div className="ml-auto min-w-0">
                                <OfflineSummaryMetrics summary={periodSummary} compact />
                            </div>
                        )}
                        {latestScore && (
                            <div className="ml-auto inline-flex items-baseline gap-2">
                                <strong className="tabular-nums">{experimentScoreLabel(latestScore)}</strong>
                                <span className="text-xs text-muted">Latest run</span>
                            </div>
                        )}
                    </div>
                    {periodSummary && (
                        <div className="grid min-h-6 grid-cols-[minmax(0,1fr)_auto] items-center gap-x-2 text-muted text-xs">
                            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                                <OfflineScoreCounts summary={periodSummary} showPassRate={false} />
                                <span>{`${periodSummary.experimentCount} ${periodSummary.experimentCount === 1 ? 'experiment' : 'experiments'} (${scoredItemCount} ${scoredItemCount === 1 ? 'item' : 'items'})`}</span>
                            </div>
                            <div className="flex items-center gap-1">
                                {versionSummaries.length > 1 && (
                                    <LemonButton
                                        size="xsmall"
                                        type="tertiary"
                                        icon={<IconChevronLeft />}
                                        aria-label="Older scorer version"
                                        tooltip="Show summary for older version"
                                        disabledReason={
                                            versionIndex === versionSummaries.length - 1
                                                ? 'Oldest version in this period'
                                                : undefined
                                        }
                                        onClick={() => selectVersion(versionSummaries[versionIndex + 1].scorer.id)}
                                        data-attr="offline-score-older-version"
                                    />
                                )}
                                <span
                                    className="text-xs text-muted tabular-nums"
                                    data-attr="offline-score-summary-version"
                                >
                                    {`v${periodSummary.scorer.version}`}
                                </span>
                                {versionSummaries.length > 1 && (
                                    <LemonButton
                                        size="xsmall"
                                        type="tertiary"
                                        icon={<IconChevronRight />}
                                        aria-label="Newer scorer version"
                                        tooltip="Show summary for newer version"
                                        disabledReason={
                                            versionIndex === 0 ? 'Newest version in this period' : undefined
                                        }
                                        onClick={() => selectVersion(versionSummaries[versionIndex - 1].scorer.id)}
                                        data-attr="offline-score-newer-version"
                                    />
                                )}
                            </div>
                        </div>
                    )}
                    {isExperimentScore && points.length > 0 && (
                        <div
                            className={
                                showChart
                                    ? 'flex min-h-6 min-w-0 flex-wrap items-center gap-x-3 gap-y-1'
                                    : 'min-w-0 space-y-1'
                            }
                        >
                            {!showChart && <div className="text-xs text-muted">Recent runs</div>}
                            {points.slice(0, showChart ? 1 : 3).map((point) => {
                                const score = point.experiment.experiment_score
                                return (
                                    score && (
                                        <div
                                            key={point.experiment.id}
                                            className="flex flex-wrap items-baseline gap-x-2 text-sm"
                                        >
                                            {!latestScore && (
                                                <strong className="tabular-nums">
                                                    {experimentScoreLabel(score, true)}
                                                </strong>
                                            )}
                                            <Link
                                                subtle
                                                to={offlineExperimentUrl(point)}
                                                data-attr="offline-experiment-trend-open-run"
                                                className="min-w-0 break-words"
                                            >
                                                {point.experiment.name}
                                            </Link>
                                            <span className="text-muted text-xs">v{score.version}</span>
                                        </div>
                                    )
                                )
                            })}
                            <div className="text-muted text-xs">{`${points.filter((point) => point.experiment.experiment_score?.status === 'ok').length} of ${points.length} ${points.length === 1 ? 'run' : 'runs'} scored`}</div>
                        </div>
                    )}
                    {hasPartialHistory && (
                        <div className="text-xs text-muted">
                            <p className="mb-1">{getOfflineHistoryCoverage(trend.page, props.timezone)}</p>
                            <p className="mb-0">Earlier experiments and scorer versions may not be shown.</p>
                        </div>
                    )}
                    {points.length > 0 && showChart && (
                        <OfflineScoreTrendChart
                            heightClassName="h-36"
                            showHeading={false}
                            combineVersions
                            passingRuleVersionId={periodSummary?.scorer.id}
                            hoverLogic={overviewLogic}
                            xDomain={props.xDomain}
                            colorOffset={props.colorOffset}
                            timezone={props.timezone}
                            periods={[
                                {
                                    key: 'overview',
                                    label: 'Experiments',
                                    points,
                                    dateFrom: props.dateFrom,
                                    dateTo: props.dateTo,
                                },
                            ]}
                            onPointClick={(point) => router.actions.push(offlineExperimentUrl(point))}
                        />
                    )}
                    {!points.length && (
                        <p className="text-muted my-4">No experiments with this score match these filters.</p>
                    )}
                </>
            ) : null}
        </LemonCard>
    )
}
