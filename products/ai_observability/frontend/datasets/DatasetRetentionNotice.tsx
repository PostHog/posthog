import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Link } from 'lib/lemon-ui/Link'

import type { DatasetRetentionEntryApi } from '../generated/api.schemas'
import { getDatasetDetailUrl } from './aiObservabilityDatasetsLogic'
import { RETENTION_PAGE_SIZE, datasetRetentionLogic } from './datasetRetentionLogic'

export function DatasetRetentionNotice(): JSX.Element | null {
    const { retention, retentionLoading, retentionError, expanded, kind, page, warning, extendingKey } =
        useValues(datasetRetentionLogic)
    const { setExpanded, setKind, setPage, loadRetention, extendRetention, reportOpen } =
        useActions(datasetRetentionLogic)
    const { searchParams } = useValues(router)

    if (!retention || !warning) {
        return null
    }

    return (
        <div className="space-y-2" data-attr="dataset-retention-notice">
            <LemonBanner type="warning">
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                    <span>{warning}</span>
                    <Link
                        to="https://posthog.com/docs/ai-evals/datasets#data-retention"
                        target="_blank"
                        title="Dataset data retention"
                        data-attr="dataset-retention-docs"
                        className="text-xs"
                    >
                        Dataset data retention
                    </Link>
                    <LemonButton
                        type="secondary"
                        size="small"
                        className="ml-auto"
                        onClick={() => setExpanded(!expanded)}
                        aria-expanded={expanded}
                        aria-controls="dataset-retention-entries"
                        data-attr="dataset-retention-toggle"
                    >
                        {expanded ? 'Hide' : 'Review'}
                    </LemonButton>
                </div>
            </LemonBanner>
            {expanded && (
                <div id="dataset-retention-entries" className="space-y-2">
                    {retentionError && (
                        <LemonBanner type="warning" action={{ children: 'Retry', onClick: loadRetention }}>
                            Couldn't refresh dataset retention. Showing the last known deadlines. Try again.
                        </LemonBanner>
                    )}
                    <div className="flex flex-wrap items-center gap-2">
                        <LemonSegmentedButton
                            size="small"
                            value={kind}
                            onChange={setKind}
                            data-attr="dataset-retention-kind"
                            options={[
                                { value: 'datasets', label: `Datasets (${retention.datasets_count})` },
                                { value: 'revisions', label: `Older revisions (${retention.revisions_count})` },
                            ]}
                        />
                        <span className="text-xs text-muted">All accessible datasets, including archived</span>
                    </div>
                    <LemonTable<DatasetRetentionEntryApi>
                        size="small"
                        loading={retentionLoading}
                        dataSource={[...retention.results]}
                        rowKey={(entry) => `${entry.dataset_id}:${entry.revision ?? 'latest'}`}
                        pagination={
                            retentionError
                                ? undefined
                                : {
                                      controlled: true,
                                      useUrl: false,
                                      currentPage: page,
                                      entryCount: retention.count,
                                      pageSize: RETENTION_PAGE_SIZE,
                                      onForward: () => setPage(page + 1),
                                      onBackward: () => setPage(page - 1),
                                  }
                        }
                        columns={[
                            {
                                title: 'Dataset',
                                key: 'dataset',
                                render: (_, entry) => (
                                    <div className="flex flex-wrap items-center gap-x-2 gap-y-1 min-w-0">
                                        <Link
                                            to={
                                                combineUrl(
                                                    getDatasetDetailUrl(entry.dataset_id, searchParams),
                                                    entry.revision !== null ? { revision: entry.revision } : {}
                                                ).url
                                            }
                                            target="_blank"
                                            targetBlankIcon
                                            onClick={() => reportOpen(entry)}
                                            data-attr="dataset-retention-open"
                                            className="font-semibold inline-flex items-center gap-1 min-w-0 max-w-80 @max-[40rem]/datasets:max-w-48"
                                            title={`Open ${entry.dataset_name}${entry.revision !== null ? `, revision ${entry.revision}` : ''} in a new tab and refresh its retention`}
                                        >
                                            <span className="truncate">{entry.dataset_name}</span>
                                            {entry.revision !== null && (
                                                <span className="shrink-0">{` · Revision ${entry.revision}`}</span>
                                            )}
                                        </Link>
                                        {entry.dataset_archived && (
                                            <LemonTag size="small" type="muted">
                                                Archived
                                            </LemonTag>
                                        )}
                                    </div>
                                ),
                            },
                            {
                                title: 'Expires',
                                key: 'expires',
                                render: (_, entry) =>
                                    entry.expires_at &&
                                    (dayjs(entry.expires_at).isBefore(dayjs()) ? (
                                        <span className="text-warning">Eligible for deletion</span>
                                    ) : (
                                        <TZLabel time={entry.expires_at} />
                                    )),
                            },
                            {
                                title: '',
                                key: 'extend',
                                width: 80,
                                render: (_, entry) => (
                                    <LemonButton
                                        size="xsmall"
                                        type="secondary"
                                        onClick={() => extendRetention(entry)}
                                        loading={extendingKey === `${entry.dataset_id}:${entry.revision ?? 'latest'}`}
                                        disabledReason={
                                            extendingKey ? 'Wait for retention to finish extending' : undefined
                                        }
                                        tooltip={
                                            entry.revision !== null
                                                ? 'Refresh this revision’s retention and its dataset’s retention'
                                                : 'Refresh this dataset’s retention. Older revisions keep their own deadlines.'
                                        }
                                        data-attr="dataset-retention-extend"
                                    >
                                        Extend
                                    </LemonButton>
                                ),
                            },
                        ]}
                    />
                </div>
            )}
        </div>
    )
}
