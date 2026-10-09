import { useActions, useValues } from 'kea'

import { IconExternal } from '@posthog/icons'
import { LemonTable, LemonTableColumns, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { urls } from 'scenes/urls'

import type { CloudAgentRunApi } from '../generated/api.schemas'
import { RUNS_PAGE_SIZE, cloudAgentsRunsLogic } from '../logics/cloudAgentsRunsLogic'
import { formatBoxSize, formatRate } from '../utils/pricing'
import { RunCostCell } from './RunCostCell'
import { RunStatusTag } from './RunStatusTag'

export function RunsTable(): JSX.Element {
    const { runs, runsCount, runsTableLoading, page, hasFilters } = useValues(cloudAgentsRunsLogic)
    const { setPage } = useActions(cloudAgentsRunsLogic)

    const columns: LemonTableColumns<CloudAgentRunApi> = [
        {
            title: 'Status',
            key: 'status',
            width: 0,
            render: (_, run) => (
                <RunStatusTag status={run.status} reason={run.status_reason} detail={run.status_detail} />
            ),
        },
        {
            title: 'Prompt',
            key: 'prompt',
            render: (_, run) => (
                <Link
                    to={urls.cloudAgentRun(run.id)}
                    className="line-clamp-2 min-w-48 max-w-120 font-semibold"
                    title={run.prompt}
                    data-attr="cloud-agents-run-link"
                >
                    {run.prompt}
                </Link>
            ),
        },
        {
            title: 'Repository',
            key: 'repository',
            render: (_, run) => (
                <div className="flex flex-col whitespace-nowrap" translate="no">
                    <span>{run.repositories[0]?.name ?? 'None'}</span>
                    {run.repositories[0]?.initial_branch && (
                        <span className="text-secondary text-xs">{run.repositories[0].initial_branch}</span>
                    )}
                </div>
            ),
        },
        {
            title: 'Preset',
            key: 'preset',
            render: (_, run) =>
                run.preset ? (
                    <Link to={urls.cloudAgentPreset(run.preset.id)} className="whitespace-nowrap">
                        {run.preset.name}
                    </Link>
                ) : (
                    <span className="text-secondary">None</span>
                ),
        },
        {
            title: 'Box size',
            key: 'size',
            render: (_, run) => (
                <div className="flex flex-col whitespace-nowrap" translate="no">
                    <span>{formatBoxSize(run.config.size)}</span>
                    <span className="text-secondary text-xs">
                        {formatRate(run.config.size.price_per_hour_usd)} per hour
                    </span>
                </div>
            ),
        },
        {
            title: 'Cost',
            key: 'cost',
            render: (_, run) => <RunCostCell cost={run.cost} />,
        },
        {
            title: 'Pull request',
            key: 'pr',
            render: (_, run) =>
                run.result.pr_url ? (
                    <Link to={run.result.pr_url} target="_blank" className="whitespace-nowrap">
                        View <IconExternal />
                    </Link>
                ) : (
                    <span className="text-secondary">None</span>
                ),
        },
        {
            title: 'Started',
            key: 'started',
            render: (_, run) => <TZLabel time={run.started_at ?? run.created_at} />,
        },
    ]

    return (
        <LemonTable
            dataSource={runs}
            columns={columns}
            rowKey="id"
            loading={runsTableLoading}
            emptyState={
                hasFilters
                    ? 'No runs match these filters. Change or clear the filters to see more runs.'
                    : 'No runs yet. Start a run to see it here.'
            }
            pagination={{
                controlled: true,
                pageSize: RUNS_PAGE_SIZE,
                currentPage: page,
                entryCount: runsCount,
                onForward: () => setPage(page + 1),
                onBackward: () => setPage(page - 1),
            }}
            data-attr="cloud-agents-runs-table"
        />
    )
}
