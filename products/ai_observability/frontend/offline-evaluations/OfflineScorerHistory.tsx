import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useState } from 'react'

import { LemonBanner, LemonButton, LemonCard, LemonLabel, LemonSelect, LemonTag, Spinner } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { TZLabel } from 'lib/components/TZLabel'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { EvaluationsTabs } from '../evaluations/EvaluationsTabs'
import { ScoreDefinitionVersionButton } from '../scoreDefinitions/ScoreDefinitionVersionButton'
import { offlineExperimentUrl } from './offlineExperimentPresentation'
import { offlineScorerHistoryLogic, type OfflineScorerHistoryProps } from './offlineScorerHistoryLogic'
import { OfflineScorerHistoryTable } from './OfflineScorerHistoryTable'
import { OfflineScoreTrendChart } from './OfflineScoreTrendChart'
import { getOfflineHistoryCoverage, offlineScoreConfigurationLabel } from './offlineScoreTrends'

export function OfflineScorerHistory(props: OfflineScorerHistoryProps): JSX.Element {
    const [expandedRuns, setExpandedRuns] = useState<Set<string>>(new Set())
    const logic = offlineScorerHistoryLogic(props)
    const {
        definition,
        definitionLoading,
        definitionError,
        versions,
        versionsLoading,
        versionsError,
        versionOptions,
        filters,
        selectedVersion,
        selectedVersionLoading,
        selectedVersionError,
        windows,
        primaryPage,
        primaryPageLoading,
        primaryError,
        comparisonPage,
        comparisonPageLoading,
        comparisonError,
        primaryCursors,
        comparisonCursors,
        trendPeriods,
        timezone,
    } = useValues(logic)
    const {
        setFilters,
        loadOfflineHistoryDefinition,
        loadOfflineHistoryVersions,
        loadOfflineHistoryVersion,
        refreshHistory,
        changePage,
        loadOfflineHistoryPrimaryPage,
        loadOfflineHistoryComparisonPage,
        reloadOfflineHistoryDefinition,
    } = useActions(logic)

    const toggleRun = (key: string): void => {
        setExpandedRuns((previous) => {
            const next = new Set(previous)
            next.has(key) ? next.delete(key) : next.add(key)
            return next
        })
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name={definition?.name || 'Scorer history'}
                description="Scores across offline experiments"
                resourceType={{ type: 'llm_analytics' }}
            />
            <EvaluationsTabs activeTab="scorers">
                {definitionLoading ? (
                    <Spinner />
                ) : definitionError ? (
                    <LemonBanner
                        type="error"
                        action={{ children: 'Retry', onClick: () => loadOfflineHistoryDefinition() }}
                    >
                        {definitionError}
                    </LemonBanner>
                ) : !definition ? (
                    <Spinner />
                ) : (
                    <div className="space-y-4 min-w-0">
                        <div className="flex items-center justify-between flex-wrap gap-2">
                            <div className="flex items-center flex-wrap gap-2">
                                <LemonTag>{definition.kind}</LemonTag>
                                {definition.archived && <LemonTag type="warning">Archived</LemonTag>}
                                <span className="text-muted">{definition.description}</span>
                            </div>
                            <ScoreDefinitionVersionButton
                                definition={definition}
                                onSuccess={reloadOfflineHistoryDefinition}
                            />
                        </div>
                        <div className="flex flex-wrap gap-2 items-end">
                            <div>
                                <LemonLabel>Upload state</LemonLabel>
                                <LemonSelect
                                    value={filters.statuses}
                                    onChange={(statuses) => setFilters({ statuses })}
                                    options={[
                                        { value: 'completed', label: 'Completed' },
                                        { value: 'uploading', label: 'Uploading' },
                                        { value: 'failed', label: 'Failed' },
                                        { value: 'completed,uploading,failed', label: 'All states' },
                                    ]}
                                />
                            </div>
                            <div>
                                <LemonLabel>Source</LemonLabel>
                                <LemonSelect
                                    value={filters.run_source}
                                    onChange={(run_source) => setFilters({ run_source })}
                                    options={[
                                        { value: '', label: 'All sources' },
                                        { value: 'ci', label: 'CI' },
                                        { value: 'local', label: 'Local' },
                                        { value: 'scheduled', label: 'Scheduled' },
                                        { value: 'not_specified', label: 'Not specified' },
                                    ]}
                                />
                            </div>
                            <div>
                                <LemonLabel>Version</LemonLabel>
                                <LemonSelect
                                    value={filters.version}
                                    options={versionOptions}
                                    onChange={(version) => setFilters({ version })}
                                    loading={selectedVersionLoading || versionsLoading}
                                    data-attr="offline-history-version"
                                />
                            </div>
                            {versions?.next_cursor && (
                                <LemonButton
                                    type="secondary"
                                    loading={versionsLoading}
                                    onClick={() => loadOfflineHistoryVersions({ cursor: versions.next_cursor! })}
                                >
                                    Load older versions
                                </LemonButton>
                            )}
                            <div>
                                <LemonLabel>Date range</LemonLabel>
                                <DateFilter
                                    dateFrom={filters.date_from}
                                    dateTo={filters.date_to}
                                    onChange={(date_from, date_to) =>
                                        setFilters({ date_from: date_from || 'all', date_to })
                                    }
                                    showCustom
                                />
                            </div>
                            <div>
                                <LemonLabel>Compare</LemonLabel>
                                <LemonSelect
                                    value={filters.compare}
                                    onChange={(compare) => setFilters({ compare })}
                                    options={[
                                        { value: 'none', label: 'No comparison' },
                                        {
                                            value: 'previous',
                                            label: 'Previous period',
                                            disabledReason:
                                                filters.date_from === 'all'
                                                    ? 'Choose a bounded date range to compare the previous period.'
                                                    : undefined,
                                        },
                                        { value: 'custom', label: 'Custom period' },
                                    ]}
                                    data-attr="offline-history-compare"
                                />
                            </div>
                            {filters.compare === 'custom' && (
                                <div>
                                    <LemonLabel>Comparison range</LemonLabel>
                                    <DateFilter
                                        dateFrom={filters.compare_from}
                                        dateTo={filters.compare_to}
                                        onChange={(compare_from, compare_to) =>
                                            setFilters({ compare_from: compare_from || 'all', compare_to })
                                        }
                                        showCustom
                                    />
                                </div>
                            )}
                            <LemonButton
                                type="secondary"
                                loading={primaryPageLoading || comparisonPageLoading}
                                onClick={refreshHistory}
                                data-attr="offline-history-refresh"
                            >
                                Refresh
                            </LemonButton>
                        </div>
                        {versionsError && (
                            <LemonBanner
                                type="error"
                                action={{ children: 'Retry', onClick: () => loadOfflineHistoryVersions({}) }}
                            >
                                {versionsError}
                            </LemonBanner>
                        )}
                        {selectedVersionError && (
                            <LemonBanner
                                type="error"
                                action={{ children: 'Retry', onClick: () => loadOfflineHistoryVersion() }}
                            >
                                {selectedVersionError}
                            </LemonBanner>
                        )}
                        {selectedVersion && !selectedVersionLoading && !selectedVersionError && (
                            <div className="text-xs text-muted space-y-1">
                                <div className="break-all">{`Version ${selectedVersion.version} · ${selectedVersion.id}`}</div>
                                <div>{offlineScoreConfigurationLabel(selectedVersion)}</div>
                            </div>
                        )}
                        {windows.error ? (
                            <LemonBanner type="error">{windows.error}</LemonBanner>
                        ) : (
                            <>
                                <LemonCard hoverEffect={false} className="min-w-0">
                                    <div className="font-semibold mb-2">Score history</div>
                                    {primaryPageLoading || comparisonPageLoading || (!primaryPage && !primaryError) ? (
                                        <Spinner />
                                    ) : (
                                        <>
                                            {(primaryError || comparisonError) && (
                                                <LemonBanner type="error">
                                                    Some score history could not load. Retry the affected period below.
                                                </LemonBanner>
                                            )}
                                            {trendPeriods.length > 0 && (
                                                <OfflineScoreTrendChart
                                                    periods={trendPeriods}
                                                    timezone={timezone}
                                                    onPointClick={(point) =>
                                                        router.actions.push(offlineExperimentUrl(point))
                                                    }
                                                />
                                            )}
                                        </>
                                    )}
                                    <p className="text-muted text-xs mt-2 mb-0">
                                        Each point is one experiment and scorer version. Points use successful results
                                        only. Different periods and versions remain separate.
                                    </p>
                                </LemonCard>
                                {[
                                    {
                                        key: 'primary' as const,
                                        title: 'Selected period',
                                        page: primaryPage,
                                        loading: primaryPageLoading,
                                        error: primaryError,
                                        cursors: primaryCursors,
                                        retry: loadOfflineHistoryPrimaryPage,
                                        range: windows.primary,
                                    },
                                    ...(filters.compare !== 'none'
                                        ? [
                                              {
                                                  key: 'comparison' as const,
                                                  title: 'Comparison period',
                                                  page: comparisonPage,
                                                  loading: comparisonPageLoading,
                                                  error: comparisonError,
                                                  cursors: comparisonCursors,
                                                  retry: loadOfflineHistoryComparisonPage,
                                                  range: windows.comparison,
                                              },
                                          ]
                                        : []),
                                ].map((period) => (
                                    <section key={period.key} className="space-y-2 min-w-0">
                                        <div className="font-semibold">{period.title}</div>
                                        <div className="text-xs text-muted flex flex-wrap gap-1">
                                            {period.range?.dateFrom ? (
                                                <TZLabel time={period.range.dateFrom} displayTimezone={timezone} />
                                            ) : (
                                                <span>All time</span>
                                            )}
                                            <span>to</span>
                                            {period.range?.dateTo && (
                                                <TZLabel time={period.range.dateTo} displayTimezone={timezone} />
                                            )}
                                        </div>
                                        {period.error ? (
                                            <LemonBanner
                                                type="error"
                                                action={{ children: 'Retry', onClick: () => period.retry() }}
                                            >
                                                {period.error}
                                            </LemonBanner>
                                        ) : (
                                            <>
                                                {period.page && (
                                                    <div className="text-xs text-muted">
                                                        {getOfflineHistoryCoverage(period.page, timezone)}
                                                    </div>
                                                )}
                                                <OfflineScorerHistoryTable
                                                    periodKey={period.key}
                                                    page={period.page}
                                                    loading={period.loading}
                                                    expandedRuns={expandedRuns}
                                                    onToggleRun={toggleRun}
                                                />
                                            </>
                                        )}
                                        <div className="flex flex-wrap gap-2 justify-end">
                                            <LemonButton
                                                type="secondary"
                                                disabledReason={
                                                    period.cursors.length <= 1
                                                        ? 'You are viewing the newest page.'
                                                        : undefined
                                                }
                                                loading={period.loading}
                                                onClick={() => changePage(period.key, null)}
                                            >
                                                Newer results
                                            </LemonButton>
                                            <LemonButton
                                                type="secondary"
                                                disabledReason={
                                                    !period.page?.next_cursor || !!period.error
                                                        ? 'No older page is available.'
                                                        : undefined
                                                }
                                                loading={period.loading}
                                                onClick={() =>
                                                    period.page?.next_cursor &&
                                                    changePage(period.key, period.page.next_cursor)
                                                }
                                            >
                                                Older results
                                            </LemonButton>
                                        </div>
                                    </section>
                                ))}
                            </>
                        )}
                    </div>
                )}
            </EvaluationsTabs>
        </SceneContent>
    )
}
