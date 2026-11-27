import { IconChevronDown, IconChevronRight } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { TZLabel } from 'lib/components/TZLabel'

import type { OfflineHistoryPageApi, OfflineHistoryPointApi } from '../generated/api.schemas'
import { experimentScoreLabel } from './ExperimentScoreResult'
import { offlineExperimentUrl } from './offlineExperimentPresentation'
import {
    OFFLINE_HISTORY_BREAKDOWN_LABELS,
    offlineBreakdownValueLabel,
    offlineHistoryPointKey,
    type OfflineHistoryBreakdown,
} from './offlineHistoryBreakdown'
import { OfflineScorerHistoryRunDetails } from './OfflineScorerHistoryRunDetails'
import { OfflineScoreSummaryDisplay } from './OfflineScoreSummaryDisplay'
import { offlineUnscoredLabel } from './offlineUnscoredLabel'

export function OfflineScorerHistoryTable({
    periodKey,
    breakdown,
    page,
    loading,
    expandedRuns,
    onToggleRun,
    experimentScope,
}: {
    periodKey: string
    breakdown?: OfflineHistoryBreakdown
    page: OfflineHistoryPageApi | null
    loading: boolean
    expandedRuns: ReadonlySet<string>
    onToggleRun: (key: string) => void
    experimentScope: boolean
}): JSX.Element {
    return (
        <LemonTable<OfflineHistoryPointApi>
            className="@max-[50rem]/scorer-history:[&_colgroup]:hidden @max-[50rem]/scorer-history:[&_table]:table-auto"
            rowKey={offlineHistoryPointKey}
            dataSource={page?.results || []}
            loading={loading || !page}
            size="small"
            tableLayout="fixed"
            emptyState="No experiments match these filters."
            columns={[
                {
                    title: 'Experiment',
                    key: 'name',
                    className: '@max-[50rem]/scorer-history:w-2/5 @max-[50rem]/scorer-history:max-w-0',
                    width: breakdown ? '24%' : '28%',
                    render: (_, point) => {
                        const key = `${periodKey}:${offlineHistoryPointKey(point)}`
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
                                    <Link
                                        to={offlineExperimentUrl(point)}
                                        className="truncate min-w-0"
                                        data-attr="offline-history-open-experiment"
                                    >
                                        {point.experiment.name}
                                    </Link>
                                </Tooltip>
                            </div>
                        )
                    },
                },
                ...(breakdown
                    ? [
                          {
                              title: OFFLINE_HISTORY_BREAKDOWN_LABELS[breakdown],
                              key: 'breakdown',
                              className: '@max-[50rem]/scorer-history:w-1/5 @max-[50rem]/scorer-history:max-w-0',
                              width: '16%',
                              render: (_: unknown, point: OfflineHistoryPointApi) => (
                                  <Tooltip title={offlineBreakdownValueLabel(point.breakdown_value, breakdown)}>
                                      <div className="truncate">
                                          {offlineBreakdownValueLabel(point.breakdown_value, breakdown)}
                                      </div>
                                  </Tooltip>
                              ),
                          },
                      ]
                    : []),
                {
                    title: 'Tags',
                    key: 'tags',
                    width: breakdown ? '18%' : '24%',
                    render: (_, point) => (
                        <div className="min-w-0 max-w-64">
                            <ObjectTags tags={point.experiment.tags} staticOnly maxVisibleTags={2} wrap />
                        </div>
                    ),
                },
                {
                    title: 'Execution',
                    key: 'execution',
                    className: '@max-[50rem]/scorer-history:hidden',
                    width: breakdown ? '14%' : '16%',
                    render: (_, point) => (
                        <div className="truncate text-xs">
                            <TZLabel time={point.experiment.started_at} />
                        </div>
                    ),
                },
                {
                    title: 'Score',
                    key: 'score',
                    width: breakdown ? '14%' : '12%',
                    render: (_, point) =>
                        point.summary ? (
                            <OfflineScoreSummaryDisplay summary={point.summary} />
                        ) : (
                            point.experiment.experiment_score && (
                                <div className="flex flex-wrap items-center gap-1">
                                    <strong>{experimentScoreLabel(point.experiment.experiment_score)}</strong>
                                    <LemonTag type="muted" size="small">
                                        v{point.experiment.experiment_score.version}
                                    </LemonTag>
                                </div>
                            )
                        ),
                },
                {
                    title: experimentScope ? 'Items' : 'Coverage',
                    key: 'coverage',
                    className: '@max-[40rem]/scorer-history:hidden',
                    width: breakdown ? '14%' : '20%',
                    render: (_, { experiment, summary }) =>
                        summary ? (
                            <Tooltip
                                title={`${summary.status_counts.ok} / ${summary.observed_item_count} scored items · ${summary.status_counts.error} errors · ${summary.status_counts.skipped} skipped · ${summary.status_counts.not_applicable} not applicable · ${offlineUnscoredLabel(summary)}`}
                            >
                                <div className="text-xs truncate">
                                    <span>{`${summary.status_counts.ok}/${summary.observed_item_count} scored · `}</span>
                                    <span
                                        className={summary.status_counts.error > 0 ? 'text-danger' : 'text-muted'}
                                    >{`${summary.status_counts.error} errors`}</span>
                                    <span className="text-muted">{` · ${offlineUnscoredLabel(summary)}`}</span>
                                </div>
                            </Tooltip>
                        ) : (
                            experiment.accepted_item_count
                        ),
                },
            ]}
            expandable={{
                noIndent: true,
                showRowExpansionToggle: false,
                isRowExpanded: (point) => expandedRuns.has(`${periodKey}:${offlineHistoryPointKey(point)}`),
                expandedRowRender: (point) => <OfflineScorerHistoryRunDetails point={point} />,
            }}
        />
    )
}
