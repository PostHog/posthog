import { IconChevronDown, IconChevronRight } from '@posthog/icons'
import { LemonButton, LemonTable, Link, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import type { OfflineHistoryPageApi, OfflineHistoryPointApi } from '../generated/api.schemas'
import { offlineExperimentUrl } from './offlineExperimentPresentation'
import { OfflineScorerHistoryRunDetails } from './OfflineScorerHistoryRunDetails'
import { OfflineScoreSummaryDisplay } from './OfflineScoreSummaryDisplay'

export function OfflineScorerHistoryTable({
    periodKey,
    page,
    loading,
    expandedRuns,
    onToggleRun,
}: {
    periodKey: string
    page: OfflineHistoryPageApi | null
    loading: boolean
    expandedRuns: ReadonlySet<string>
    onToggleRun: (key: string) => void
}): JSX.Element {
    return (
        <LemonTable<OfflineHistoryPointApi>
            rowKey={(point) => `${point.experiment.id}:${point.summary.scorer.id}`}
            dataSource={page?.results || []}
            loading={loading || !page}
            size="small"
            tableLayout="fixed"
            emptyState="No results in this period. Try another version or date range."
            columns={[
                {
                    title: 'Experiment',
                    key: 'name',
                    width: '28%',
                    render: (_, point) => {
                        const key = `${periodKey}:${point.experiment.id}:${point.summary.scorer.id}`
                        return (
                            <div className="flex items-center gap-1 min-w-0">
                                <LemonButton
                                    type="tertiary"
                                    size="xsmall"
                                    noPadding
                                    icon={expandedRuns.has(key) ? <IconChevronDown /> : <IconChevronRight />}
                                    aria-label={`Run details for ${point.experiment.name}`}
                                    tooltip={expandedRuns.has(key) ? 'Hide details' : 'Run details'}
                                    aria-expanded={expandedRuns.has(key)}
                                    data-attr="offline-history-run-details"
                                    onClick={() => onToggleRun(key)}
                                />
                                <Tooltip title={point.experiment.name}>
                                    <Link to={offlineExperimentUrl(point)} className="truncate min-w-0">
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
                    render: (_, point) => <OfflineScoreSummaryDisplay summary={point.summary} />,
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
                                    className={summary.status_counts.error > 0 ? 'text-danger' : 'text-muted'}
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
                    expandedRuns.has(`${periodKey}:${point.experiment.id}:${point.summary.scorer.id}`),
                expandedRowRender: (point) => <OfflineScorerHistoryRunDetails point={point} />,
            }}
        />
    )
}
