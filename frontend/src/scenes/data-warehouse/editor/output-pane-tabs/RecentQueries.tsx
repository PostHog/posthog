import { useActions, useValues } from 'kea'

import { IconArrowRight, IconRefresh } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonTable, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import { OutputTab, outputPaneLogic } from '../outputPaneLogic'
import { sqlEditorLogic } from '../sqlEditorLogic'
import { RECENT_QUERIES_DAYS, RecentQuery, recentQueriesLogic } from './recentQueriesLogic'

export function RecentQueries(): JSX.Element {
    const { recentQueries, recentQueriesLoading, recentQueriesError } = useValues(recentQueriesLogic)
    const { loadRecentQueries } = useActions(recentQueriesLogic)
    const { createTab } = useActions(sqlEditorLogic)
    const { setActiveTab } = useActions(outputPaneLogic)

    const openInNewTab = (query: string): void => {
        createTab(query)
        // The output pane is shared across editor tabs, so the new tab would open on this list.
        setActiveTab(OutputTab.Results)
    }

    return (
        <div className="flex flex-col flex-1 min-h-0 w-full border-t overflow-auto">
            <div className="flex flex-wrap gap-2 justify-between items-center px-4 py-2">
                <span className="text-secondary">
                    Queries you ran in the SQL editor over the past {RECENT_QUERIES_DAYS} days
                </span>
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconRefresh />}
                    onClick={loadRecentQueries}
                    loading={recentQueriesLoading}
                    data-attr="sql-editor-recent-queries-refresh"
                >
                    Refresh
                </LemonButton>
            </div>
            {recentQueriesError ? (
                <LemonBanner type="error" className="mx-4 mb-2">
                    We could not load your recent queries. Try again in a moment.
                </LemonBanner>
            ) : null}
            <LemonTable
                dataSource={recentQueries ?? []}
                loading={recentQueriesLoading || (recentQueries === null && !recentQueriesError)}
                rowKey={(record: RecentQuery) => `${record.last_run_at}-${record.query}`}
                emptyState="Nothing here yet. Run a query and it shows up in this list."
                columns={[
                    {
                        title: 'Last run',
                        key: 'last_run_at',
                        width: 140,
                        render: (_, record) => <TZLabel time={record.last_run_at} />,
                    },
                    {
                        title: 'Status',
                        key: 'last_exception_code',
                        width: 100,
                        render: (_, record) =>
                            record.last_exception_code === 0 ? (
                                <LemonTag type="success">Succeeded</LemonTag>
                            ) : (
                                <LemonTag type="danger">Failed</LemonTag>
                            ),
                    },
                    {
                        title: 'Query',
                        key: 'query',
                        render: (_, record) => (
                            <div className="font-mono text-xs whitespace-pre-wrap line-clamp-3">{record.query}</div>
                        ),
                    },
                    {
                        title: '',
                        key: 'load',
                        width: 40,
                        render: (_, record) => (
                            <Tooltip title="Open this query in a new editor tab">
                                <LemonButton
                                    size="xsmall"
                                    icon={<IconArrowRight />}
                                    onClick={() => openInNewTab(record.query)}
                                    data-attr="sql-editor-recent-queries-load"
                                />
                            </Tooltip>
                        ),
                    },
                ]}
            />
        </div>
    )
}
