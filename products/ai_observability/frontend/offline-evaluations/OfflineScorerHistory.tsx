import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'
import { useState } from 'react'

import { IconChevronDown, IconChevronRight } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonCard,
    LemonLabel,
    LemonSelect,
    LemonTable,
    LemonTag,
    Link,
    Spinner,
    Tooltip,
} from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { TZLabel } from 'lib/components/TZLabel'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { EvaluationsTabs } from '../evaluations/EvaluationsTabs'
import type { OfflineHistoryPointApi } from '../generated/api.schemas'
import { ScoreDefinitionVersionButton } from '../scoreDefinitions/ScoreDefinitionVersionButton'
import { offlineScorerHistoryLogic, type OfflineScorerHistoryProps } from './offlineScorerHistoryLogic'
import { OfflineScoreTrendChart } from './OfflineScoreTrendChart'
import { formatOfflineScore, getOfflineHistoryCoverage, offlineScoreConfigurationLabel } from './offlineScoreTrends'

function experimentUrl(point: OfflineHistoryPointApi): string {
    return combineUrl(urls.aiObservabilityOfflineEvaluationExperiment(point.experiment.id), {
        scorer_version_id: point.summary.scorer.id,
    }).url
}

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
                                                    onPointClick={(point) => router.actions.push(experimentUrl(point))}
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
                                                <LemonTable<OfflineHistoryPointApi>
                                                    rowKey={(point) =>
                                                        `${point.experiment.id}:${point.summary.scorer.id}`
                                                    }
                                                    dataSource={period.page?.results || []}
                                                    loading={period.loading || !period.page}
                                                    size="small"
                                                    tableLayout="fixed"
                                                    emptyState="No results in this period. Try another version or date range."
                                                    columns={[
                                                        {
                                                            title: 'Experiment',
                                                            key: 'name',
                                                            width: '28%',
                                                            render: (_, point) => {
                                                                const key = `${period.key}:${point.experiment.id}:${point.summary.scorer.id}`
                                                                return (
                                                                    <div className="flex items-center gap-1 min-w-0">
                                                                        <LemonButton
                                                                            type="tertiary"
                                                                            size="xsmall"
                                                                            noPadding
                                                                            icon={
                                                                                expandedRuns.has(key) ? (
                                                                                    <IconChevronDown />
                                                                                ) : (
                                                                                    <IconChevronRight />
                                                                                )
                                                                            }
                                                                            aria-label={`Run details for ${point.experiment.name}`}
                                                                            tooltip={
                                                                                expandedRuns.has(key)
                                                                                    ? 'Hide details'
                                                                                    : 'Run details'
                                                                            }
                                                                            aria-expanded={expandedRuns.has(key)}
                                                                            data-attr="offline-history-run-details"
                                                                            onClick={() =>
                                                                                setExpandedRuns((previous) => {
                                                                                    const next = new Set(previous)
                                                                                    next.has(key)
                                                                                        ? next.delete(key)
                                                                                        : next.add(key)
                                                                                    return next
                                                                                })
                                                                            }
                                                                        />
                                                                        <Tooltip title={point.experiment.name}>
                                                                            <Link
                                                                                to={experimentUrl(point)}
                                                                                className="truncate min-w-0"
                                                                            >
                                                                                {point.experiment.name}
                                                                            </Link>
                                                                        </Tooltip>
                                                                    </div>
                                                                )
                                                            },
                                                        },
                                                        {
                                                            title: 'Execution',
                                                            key: 'execution',
                                                            width: '20%',
                                                            render: (_, point) => (
                                                                <div className="truncate text-xs">
                                                                    <TZLabel time={point.experiment.started_at} />
                                                                </div>
                                                            ),
                                                        },
                                                        {
                                                            title: 'Score',
                                                            key: 'score',
                                                            width: '16%',
                                                            render: (_, point) => (
                                                                <Tooltip title={formatOfflineScore(point.summary)}>
                                                                    <span className="block tabular-nums truncate">
                                                                        {formatOfflineScore(point.summary)}
                                                                    </span>
                                                                </Tooltip>
                                                            ),
                                                        },
                                                        {
                                                            title: 'Coverage',
                                                            key: 'coverage',
                                                            width: '36%',
                                                            render: (_, { summary }) => (
                                                                <Tooltip
                                                                    title={`${summary.status_counts.ok} / ${summary.observed_item_count} scored items · ${summary.status_counts.error} errors · ${summary.status_counts.skipped} skipped · ${summary.status_counts.not_applicable} not applicable · ${summary.missing_result_count} missing`}
                                                                >
                                                                    <div className="text-xs truncate">
                                                                        <span>{`${summary.status_counts.ok}/${summary.observed_item_count} scored · `}</span>
                                                                        <span
                                                                            className={
                                                                                summary.status_counts.error > 0
                                                                                    ? 'text-danger'
                                                                                    : 'text-muted'
                                                                            }
                                                                        >{`${summary.status_counts.error} errors`}</span>
                                                                        <span className="text-muted">{` · ${summary.missing_result_count} missing`}</span>
                                                                    </div>
                                                                </Tooltip>
                                                            ),
                                                        },
                                                    ]}
                                                    expandable={{
                                                        noIndent: true,
                                                        showRowExpansionToggle: false,
                                                        isRowExpanded: (point) =>
                                                            expandedRuns.has(
                                                                `${period.key}:${point.experiment.id}:${point.summary.scorer.id}`
                                                            ),
                                                        expandedRowRender: ({ experiment, summary }) => (
                                                            <div className="space-y-3 p-2">
                                                                <div className="flex flex-wrap items-center gap-2">
                                                                    <span className="font-semibold">Run details</span>
                                                                    <LemonTag
                                                                        type={
                                                                            experiment.status === 'failed'
                                                                                ? 'danger'
                                                                                : experiment.status === 'uploading'
                                                                                  ? 'warning'
                                                                                  : 'success'
                                                                        }
                                                                    >
                                                                        {
                                                                            {
                                                                                completed: 'Completed',
                                                                                uploading: 'Uploading',
                                                                                failed: 'Failed',
                                                                            }[experiment.status]
                                                                        }
                                                                    </LemonTag>
                                                                    <span className="text-muted">
                                                                        {experiment.run_source
                                                                            ? {
                                                                                  ci: 'CI',
                                                                                  local: 'Local',
                                                                                  scheduled: 'Scheduled',
                                                                              }[experiment.run_source]
                                                                            : 'Source not specified'}
                                                                    </span>
                                                                </div>
                                                                <div className="text-xs space-y-1">
                                                                    <div className="break-words">{`Score: ${formatOfflineScore(summary)}`}</div>
                                                                    <div>{`${summary.status_counts.ok} successful / ${summary.observed_item_count} observed items`}</div>
                                                                    <div>{`${summary.status_counts.error} errors · ${summary.status_counts.skipped} skipped · ${summary.status_counts.not_applicable} not applicable · ${summary.missing_result_count} missing`}</div>
                                                                    <div>{`${summary.distinct_case_count} distinct cases · ${summary.items_with_case_key_count} with case keys · ${summary.items_without_case_key_count} without case keys`}</div>
                                                                    <div>{`${summary.trial_item_count} trial items · ${summary.distinct_trial_count} case/trial identities`}</div>
                                                                </div>
                                                                <dl className="text-xs grid gap-x-4 gap-y-2 @min-[48rem]/main-content:grid-cols-2">
                                                                    {[
                                                                        ['Suite', experiment.suite_key],
                                                                        ['Application', experiment.application_version],
                                                                        ['Model', experiment.model_version],
                                                                        ['Prompt', experiment.prompt_version],
                                                                        ['Dataset source', experiment.dataset_source],
                                                                        ['Dataset', experiment.dataset_identifier],
                                                                        [
                                                                            'Dataset revision',
                                                                            experiment.dataset_revision_identifier,
                                                                        ],
                                                                    ]
                                                                        .filter(([, value]) => value !== null)
                                                                        .map(([label, value]) => (
                                                                            <div key={label} className="min-w-0">
                                                                                <dt className="text-muted">{label}</dt>
                                                                                <dd className="m-0 break-words">
                                                                                    {value}
                                                                                </dd>
                                                                            </div>
                                                                        ))}
                                                                </dl>
                                                            </div>
                                                        ),
                                                    }}
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
