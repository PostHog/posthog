import { useActions, useValues, type BuiltLogic } from 'kea'
import { combineUrl, router } from 'kea-router'

import { IconChevronLeft, IconChevronRight } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCard, LemonSkeleton, LemonTag, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import type { offlineExperimentsLogicType } from './offlineExperimentsLogic'
import { offlineOverviewTrendLogic, type OfflineOverviewTrendLogicProps } from './offlineOverviewTrendLogic'
import { OfflineScoreTrendChart } from './OfflineScoreTrendChart'
import { formatOfflineScore, getOfflineHistoryCoverage, offlineScoreMetricLabel } from './offlineScoreTrends'

export function OfflineOverviewTrend(
    props: OfflineOverviewTrendLogicProps & {
        timezone: string
        colorOffset?: number
        hoverLogic?: BuiltLogic<offlineExperimentsLogicType>
    }
): JSX.Element {
    const logic = offlineOverviewTrendLogic(props)
    const { trend, trendLoading, trendError, versions, activeVersion, versionPoints } = useValues(logic)
    const { loadOfflineOverviewTrend, selectVersion } = useActions(logic)
    const latest = versionPoints[0]?.summary
    const versionIndex = versions.findIndex((version) => version.id === activeVersion?.id)
    const hasPartialHistory = !!trend && trend.page.count > trend.page.results.length

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
                        <h3 className="mb-0 min-w-0 truncate">
                            <Link
                                to={
                                    combineUrl(urls.aiObservabilityOfflineScorerHistory(props.scorerId), {
                                        ...props.filters,
                                        version: activeVersion?.id,
                                        date_from: props.dateFrom || 'all',
                                        date_to: props.dateTo,
                                    }).url
                                }
                                data-attr="offline-score-view-history"
                            >
                                {trend.definition.name}
                            </Link>
                        </h3>
                        <LemonTag type="muted">{trend.definition.kind}</LemonTag>
                        {versions.length > 1 && activeVersion && (
                            <div className="flex items-center gap-1 ml-auto">
                                <LemonButton
                                    size="xsmall"
                                    type="tertiary"
                                    icon={<IconChevronLeft />}
                                    aria-label="Older scorer version"
                                    tooltip="Older version"
                                    disabledReason={
                                        versionIndex === versions.length - 1
                                            ? hasPartialHistory
                                                ? 'Oldest loaded version'
                                                : 'Oldest version in this period'
                                            : undefined
                                    }
                                    onClick={() => selectVersion(versions[versionIndex + 1].id)}
                                    data-attr="offline-score-older-version"
                                />
                                <span className="text-xs text-muted tabular-nums">{`v${activeVersion.version}`}</span>
                                <LemonButton
                                    size="xsmall"
                                    type="tertiary"
                                    icon={<IconChevronRight />}
                                    aria-label="Newer scorer version"
                                    tooltip="Newer version"
                                    disabledReason={
                                        versionIndex === 0
                                            ? hasPartialHistory
                                                ? 'Newest loaded version'
                                                : 'Newest version in this period'
                                            : undefined
                                    }
                                    onClick={() => selectVersion(versions[versionIndex - 1].id)}
                                    data-attr="offline-score-newer-version"
                                />
                            </div>
                        )}
                    </div>
                    {latest && (
                        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                            <strong>{formatOfflineScore(latest)}</strong>
                            <span className="text-muted text-xs">{`${offlineScoreMetricLabel(latest.scorer)} · ${latest.status_counts.ok} scored ${latest.status_counts.ok === 1 ? 'item' : 'items'}`}</span>
                        </div>
                    )}
                    {hasPartialHistory && (
                        <div className="text-xs text-muted">
                            <p className="mb-1">{getOfflineHistoryCoverage(trend.page, props.timezone)}</p>
                            <p className="mb-0">Earlier experiments and scorer versions may not be shown.</p>
                        </div>
                    )}
                    {versionPoints.length ? (
                        <OfflineScoreTrendChart
                            heightClassName="h-36"
                            hoverLogic={props.hoverLogic}
                            colorOffset={props.colorOffset}
                            timezone={props.timezone}
                            periods={[
                                {
                                    key: 'overview',
                                    label: 'Experiments',
                                    points: versionPoints,
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
                </>
            ) : null}
        </LemonCard>
    )
}
