import { useActions, useValues } from 'kea'

import { IconRefresh, IconSearch } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonInput,
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
import { OfflineExperimentsEmptyState } from './OfflineExperimentsEmptyState'
import { offlineExperimentsLogic, type OfflineExperimentsLogicProps } from './offlineExperimentsLogic'
import { offlineRunSourceLabel } from './offlineOverviewState'
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
        hasExperiments,
        trendFilters,
        dateRange,
        cursorStack,
        refreshKey,
    } = useValues(logic)
    const { setFilters, openChooser, nextPage, previousPage, refresh } = useActions(logic)
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

    if (hasExperiments === null && !experimentsError) {
        return <LemonSkeleton className="h-80" />
    }
    if (hasExperiments === false && !experimentsLoading && !experimentsError) {
        return <OfflineExperimentsEmptyState />
    }

    return (
        <div className="@container space-y-6 min-w-0">
            <div aria-label="Experiment filters" className="flex flex-wrap items-center gap-2">
                <DateFilter
                    dateFrom={filters.date_from || '-30d'}
                    dateTo={filters.date_to || null}
                    onChange={(dateFrom, dateTo) =>
                        setFilters({ date_from: dateFrom || '-30d', date_to: dateTo || undefined })
                    }
                    showCustom
                    showCustomRelativeRange
                />
                <LemonSelect
                    value={filters.run_source || ''}
                    onChange={(run_source) => setFilters({ run_source })}
                    data-attr="offline-experiments-source-filter"
                    options={[
                        { value: '', label: 'All sources' },
                        { value: 'ci', label: 'CI' },
                        { value: 'local', label: 'Local' },
                        { value: 'scheduled', label: 'Scheduled' },
                        { value: 'not_specified', label: 'Not specified' },
                    ]}
                />
                <LemonSelect
                    value={filters.statuses || ''}
                    onChange={(statuses) => setFilters({ statuses })}
                    data-attr="offline-experiments-status-filter"
                    options={[
                        { value: '', label: 'All upload states' },
                        { value: 'uploading', label: 'Uploading' },
                        { value: 'completed', label: 'Completed' },
                        { value: 'failed', label: 'Failed' },
                    ]}
                />
                <LemonButton
                    type="secondary"
                    icon={<IconRefresh />}
                    onClick={refresh}
                    loading={experimentsLoading}
                    data-attr="offline-experiments-refresh"
                    className="ml-auto"
                >
                    Refresh
                </LemonButton>
            </div>
            <section aria-label="Score trends" className="space-y-3">
                <div className="flex flex-wrap justify-between items-center gap-2">
                    <div>
                        <h2 className="mb-0">Score trends</h2>
                        <p className="text-muted text-xs mb-0">
                            Scores across the selected experiments. Uploading and failed runs may have partial results.
                        </p>
                    </div>
                    <LemonButton type="secondary" size="small" onClick={openChooser} data-attr="offline-choose-scores">
                        Choose scores
                    </LemonButton>
                </div>
                {!dateRange ? (
                    <LemonBanner type="error">Choose a valid date range.</LemonBanner>
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
                                dateFrom={dateRange.dateFrom}
                                dateTo={dateRange.dateTo}
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
                    <LemonInput
                        type="search"
                        prefix={<IconSearch />}
                        value={filters.search || ''}
                        onChange={(search) => setFilters({ search })}
                        placeholder="Search experiments"
                    />
                </div>
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
                        emptyState="No experiments match these filters."
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
