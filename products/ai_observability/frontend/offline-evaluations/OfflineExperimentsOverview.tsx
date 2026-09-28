import { useActions, useValues } from 'kea'

import { IconRefresh, IconSearch } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonInput,
    LemonLabel,
    LemonSelect,
    LemonSkeleton,
    LemonTable,
    LemonTag,
    Link,
    Tooltip,
} from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { TZLabel } from 'lib/components/TZLabel'
import type { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { urls } from 'scenes/urls'

import type { OfflineExperimentReadApi } from '../generated/api.schemas'
import { offlineExperimentsLogic, type OfflineExperimentsLogicProps } from './offlineExperimentsLogic'
import { OFFLINE_CONTEXT_FILTERS, OFFLINE_TREND_CONTEXT_FILTERS, offlineRunSourceLabel } from './offlineOverviewState'
import { OfflineOverviewTrend } from './OfflineOverviewTrend'
import { OfflineScoreChooser } from './OfflineScoreChooser'

export function OfflineExperimentsOverview(props: OfflineExperimentsLogicProps): JSX.Element {
    const logic = offlineExperimentsLogic(props)
    const {
        experiments,
        experimentsLoading,
        experimentsError,
        filters,
        scorerIds,
        trendDates,
        trendFilters,
        trendRange,
        cursorStack,
        refreshKey,
    } = useValues(logic)
    const { setFilters, setTrendFilters, setTrendDates, openChooser, nextPage, previousPage, refresh } =
        useActions(logic)
    const hasFilters = Object.keys(filters).length > 0
    const columns: LemonTableColumns<OfflineExperimentReadApi> = [
        {
            title: 'Experiment',
            key: 'name',
            render: (_, experiment) => (
                <div className="min-w-0">
                    <Link
                        to={urls.aiObservabilityOfflineEvaluationExperiment(experiment.id)}
                        className="font-semibold break-words"
                        data-attr="offline-experiment-open"
                    >
                        {experiment.name}
                    </Link>
                    <div className="text-xs text-muted font-mono truncate" title={experiment.id}>
                        {experiment.id.slice(0, 8)}
                    </div>
                </div>
            ),
        },
        {
            title: 'Execution',
            key: 'execution',
            render: (_, experiment) => (
                <div className="space-y-1">
                    <TZLabel time={experiment.started_at} />
                    <div className="text-muted text-xs">{offlineRunSourceLabel(experiment.run_source)}</div>
                </div>
            ),
        },
        {
            title: 'Upload',
            key: 'status',
            render: (_, experiment) => (
                <LemonTag
                    type={
                        experiment.status === 'completed'
                            ? 'success'
                            : experiment.status === 'uploading'
                              ? 'warning'
                              : 'danger'
                    }
                >
                    {experiment.status === 'completed'
                        ? 'Completed'
                        : experiment.status === 'uploading'
                          ? 'Uploading'
                          : 'Failed'}
                </LemonTag>
            ),
        },
        {
            title: <Tooltip title="Result and scorer counts include only results you can access.">Coverage</Tooltip>,
            key: 'coverage',
            render: (_, experiment) => (
                <div className="text-xs space-y-1">
                    <div>{`${experiment.accepted_item_count.toLocaleString()} items`}</div>
                    <div className="text-muted">
                        {experiment.visible_result_count === null
                            ? 'Results unavailable'
                            : `${experiment.visible_result_count.toLocaleString()} visible results`}
                    </div>
                    <Tooltip
                        title={
                            experiment.visible_scorer_version_count === null
                                ? 'Scorer version count unavailable'
                                : `${experiment.visible_scorer_version_count} visible scorer versions`
                        }
                    >
                        <span className="text-muted">
                            {experiment.visible_scorer_definition_count === null
                                ? 'Scorers unavailable'
                                : `${experiment.visible_scorer_definition_count} visible scorers`}
                        </span>
                    </Tooltip>
                </div>
            ),
        },
    ]

    return (
        <div className="@container space-y-6 min-w-0">
            <section aria-label="Score trends" className="space-y-3">
                <div className="flex flex-wrap justify-between items-center gap-2">
                    <div>
                        <h2 className="mb-0">Score trends</h2>
                        <p className="text-muted text-xs mb-0">
                            Completed experiments. Each point keeps its scorer version and sample coverage.
                        </p>
                    </div>
                    <div className="flex flex-wrap gap-2">
                        <DateFilter
                            dateFrom={trendDates.dateFrom}
                            dateTo={trendDates.dateTo}
                            onChange={setTrendDates}
                            showCustom
                            showCustomRelativeRange
                        />
                        <LemonButton type="secondary" onClick={openChooser} data-attr="offline-choose-scores">
                            Choose scores
                        </LemonButton>
                    </div>
                </div>
                <details>
                    <summary className="cursor-pointer text-sm">
                        {`Filter trends${Object.keys(trendFilters).length ? ` (${Object.keys(trendFilters).length} active)` : ''}`}
                    </summary>
                    <div className="grid grid-cols-1 @min-[40rem]:grid-cols-2 @min-[64rem]:grid-cols-3 gap-3 mt-3">
                        <div>
                            <LemonLabel htmlFor="offline-trend-run-source">Run source</LemonLabel>
                            <LemonSelect
                                id="offline-trend-run-source"
                                value={trendFilters.run_source || ''}
                                onChange={(run_source) => setTrendFilters({ run_source })}
                                fullWidth
                                options={[
                                    { value: '', label: 'All sources' },
                                    { value: 'ci', label: 'CI' },
                                    { value: 'local', label: 'Local' },
                                    { value: 'scheduled', label: 'Scheduled' },
                                    { value: 'not_specified', label: 'Not specified' },
                                ]}
                            />
                        </div>
                        {OFFLINE_TREND_CONTEXT_FILTERS.map(([key, label]) => (
                            <div key={key}>
                                <LemonLabel htmlFor={`offline-trend-${key}`}>{label}</LemonLabel>
                                <LemonInput
                                    id={`offline-trend-${key}`}
                                    value={trendFilters[key] || ''}
                                    onChange={(value) => setTrendFilters({ [key]: value })}
                                    placeholder="Exact value"
                                    maxLength={255}
                                />
                            </div>
                        ))}
                    </div>
                </details>
                {Object.keys(trendFilters).length > 0 && (
                    <div className="flex flex-wrap gap-1" aria-label="Active trend filters">
                        {trendFilters.run_source && (
                            <LemonTag closable onClose={() => setTrendFilters({ run_source: undefined })}>
                                {`Run source: ${offlineRunSourceLabel(trendFilters.run_source)}`}
                            </LemonTag>
                        )}
                        {OFFLINE_TREND_CONTEXT_FILTERS.filter(([key]) => trendFilters[key]).map(([key, label]) => (
                            <LemonTag
                                key={key}
                                closable
                                onClose={() => setTrendFilters({ [key]: undefined })}
                                className="max-w-full"
                            >
                                <span className="truncate">{`${label}: ${trendFilters[key]}`}</span>
                            </LemonTag>
                        ))}
                    </div>
                )}
                {!trendRange ? (
                    <LemonBanner type="error">Choose a valid date range for the score trends.</LemonBanner>
                ) : scorerIds === null ? (
                    <LemonSkeleton className="h-40" />
                ) : scorerIds.length > 0 ? (
                    <div className="grid grid-cols-1 @min-[56rem]:grid-cols-3 gap-3">
                        {scorerIds.map((scorerId) => (
                            <OfflineOverviewTrend
                                key={scorerId}
                                teamId={props.teamId}
                                timezone={props.timezone}
                                scorerId={scorerId}
                                dateFrom={trendRange.dateFrom}
                                dateTo={trendRange.dateTo}
                                refreshKey={refreshKey}
                                filters={trendFilters}
                            />
                        ))}
                    </div>
                ) : (
                    <LemonBanner type="info" action={{ children: 'Choose scores', onClick: openChooser }}>
                        Choose recurring scores to follow their results over time.
                    </LemonBanner>
                )}
            </section>
            <section aria-label="Recent experiments" className="space-y-3">
                <div className="flex flex-wrap justify-between items-center gap-2">
                    <h2 className="mb-0">Recent experiments</h2>
                    <LemonButton
                        type="secondary"
                        icon={<IconRefresh />}
                        onClick={refresh}
                        loading={experimentsLoading}
                        data-attr="offline-experiments-refresh"
                    >
                        Refresh
                    </LemonButton>
                </div>
                <div className="flex flex-wrap gap-2">
                    <LemonInput
                        type="search"
                        prefix={<IconSearch />}
                        value={filters.search || ''}
                        onChange={(search) => setFilters({ search })}
                        placeholder="Search experiments"
                        className="flex-1 min-w-48"
                    />
                    <DateFilter
                        dateFrom={filters.date_from || 'all'}
                        dateTo={filters.date_to || null}
                        onChange={(dateFrom, dateTo) =>
                            setFilters({
                                date_from: dateFrom === 'all' ? undefined : dateFrom || undefined,
                                date_to: dateTo || undefined,
                            })
                        }
                        showCustom
                        showCustomRelativeRange
                    />
                    <LemonSelect
                        value={filters.statuses || ''}
                        onChange={(statuses) => setFilters({ statuses })}
                        options={[
                            { value: '', label: 'All upload states' },
                            { value: 'uploading', label: 'Uploading' },
                            { value: 'completed', label: 'Completed' },
                            { value: 'failed', label: 'Failed' },
                        ]}
                    />
                    <LemonSelect
                        value={filters.run_source || ''}
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
                <details>
                    <summary className="cursor-pointer text-sm">{`Filters${OFFLINE_CONTEXT_FILTERS.some(([key]) => filters[key]) ? ` (${OFFLINE_CONTEXT_FILTERS.filter(([key]) => filters[key]).length} active)` : ''}`}</summary>
                    <div className="grid grid-cols-1 @min-[40rem]:grid-cols-2 @min-[64rem]:grid-cols-3 gap-3 mt-3">
                        {OFFLINE_CONTEXT_FILTERS.map(([key, label]) => (
                            <div key={key}>
                                <LemonLabel htmlFor={`offline-filter-${key}`}>{label}</LemonLabel>
                                <LemonInput
                                    id={`offline-filter-${key}`}
                                    value={filters[key] || ''}
                                    onChange={(value) => setFilters({ [key]: value })}
                                    placeholder="Exact value"
                                />
                            </div>
                        ))}
                    </div>
                </details>
                {OFFLINE_CONTEXT_FILTERS.some(([key]) => filters[key]) && (
                    <div className="flex flex-wrap gap-1">
                        {OFFLINE_CONTEXT_FILTERS.filter(([key]) => filters[key]).map(([key, label]) => (
                            <LemonTag
                                key={key}
                                closable
                                onClose={() => setFilters({ [key]: undefined })}
                            >{`${label}: ${filters[key]}`}</LemonTag>
                        ))}
                    </div>
                )}
                {experimentsError ? (
                    <LemonBanner type="error" action={{ children: 'Retry', onClick: refresh }}>
                        {experimentsError}
                    </LemonBanner>
                ) : (
                    <LemonTable
                        dataSource={experiments?.results || []}
                        columns={columns}
                        rowKey="id"
                        loading={experimentsLoading || experiments === null}
                        tableLayout="fixed"
                        emptyState={
                            hasFilters ? (
                                'No experiments match these filters.'
                            ) : (
                                <div className="py-4 space-y-3 max-w-lg mx-auto">
                                    <h3>No offline experiments yet</h3>
                                    <p>
                                        Create a scorer and copy its version ID. Upload your experiment, items, and
                                        results with the offline evaluations API, then mark the upload as completed.
                                    </p>
                                    <p className="text-muted">
                                        Run evaluations with your own tools and send their results here.
                                    </p>
                                    <LemonButton type="primary" to={urls.aiObservabilityScorers()}>
                                        Manage scorers
                                    </LemonButton>
                                </div>
                            )
                        }
                    />
                )}
                {experiments && !experimentsError && (
                    <div className="flex flex-wrap items-center justify-between gap-2">
                        <span className="text-xs text-muted">{`${experiments.count.toLocaleString()} experiments · Page ${cursorStack.length + 1}`}</span>
                        <div className="flex gap-1">
                            <LemonButton
                                size="small"
                                onClick={previousPage}
                                disabledReason={
                                    experimentsLoading
                                        ? 'Loading experiments'
                                        : cursorStack.length === 0
                                          ? 'First page'
                                          : undefined
                                }
                            >
                                Previous
                            </LemonButton>
                            <LemonButton
                                size="small"
                                onClick={() => experiments.next_cursor && nextPage(experiments.next_cursor)}
                                disabledReason={
                                    experimentsLoading
                                        ? 'Loading experiments'
                                        : !experiments.next_cursor
                                          ? 'Last page'
                                          : undefined
                                }
                            >
                                Next
                            </LemonButton>
                        </div>
                    </div>
                )}
            </section>
            <OfflineScoreChooser {...props} />
        </div>
    )
}
