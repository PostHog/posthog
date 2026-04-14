import { useActions, useValues } from 'kea'

import { IconDatabase } from '@posthog/icons'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { SceneExport } from 'scenes/sceneTypes'
import { userLogic } from 'scenes/userLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { PrecomputationTeam, queryPerformanceLogic, SlowestQuery } from './queryPerformanceLogic'

export const scene: SceneExport = {
    component: QueryPerformance,
    logic: queryPerformanceLogic,
}

const TIME_RANGE_OPTIONS = [
    { label: '1h', hours: 1 },
    { label: '6h', hours: 6 },
    { label: '24h', hours: 24 },
    { label: '7d', hours: 168 },
]

export function QueryPerformance(): JSX.Element {
    const { user } = useValues(userLogic)
    const {
        precomputationTeams,
        precomputationTeamsLoading,
        search,
        slowestQueries,
        slowestQueriesLoading,
        hoursBack,
    } = useValues(queryPerformanceLogic)
    const { setSearch, setPrecomputation, setHoursBack, loadSlowestQueries } = useActions(queryPerformanceLogic)

    if (!user?.is_staff) {
        return (
            <>
                <SceneTitleSection
                    name="Query performance"
                    description="Internal tooling for monitoring and managing query performance across all projects."
                    resourceType={{
                        type: 'query_performance',
                        forceIcon: <IconDatabase />,
                    }}
                />
                <p>
                    Only users with staff access can view query performance tooling. Please contact your instance admin.
                </p>
                <p>
                    If you're an admin and don't have access, set <code>is_staff=true</code> for your user on the
                    PostgreSQL <code>posthog_user</code> table.
                </p>
            </>
        )
    }

    const precomputationColumns: LemonTableColumns<PrecomputationTeam> = [
        {
            title: 'Team ID',
            dataIndex: 'team_id',
            width: 100,
        },
        {
            title: 'Team name',
            dataIndex: 'team_name',
        },
        {
            title: 'Organization',
            dataIndex: 'organization_name',
        },
        {
            title: 'Organization ID',
            dataIndex: 'organization_id',
        },
        {
            title: 'Precomputation',
            width: 140,
            render: function PrecomputationToggle(_, team) {
                return (
                    <LemonSwitch
                        checked={team.experiment_precomputation_enabled}
                        onChange={(enabled) => setPrecomputation(team.team_id, enabled)}
                    />
                )
            },
        },
    ]

    const slowestQueryColumns: LemonTableColumns<SlowestQuery> = [
        {
            title: 'Time',
            dataIndex: 'timestamp',
            width: 160,
            render: function Timestamp(_, item) {
                return <span className="font-mono text-xs">{item.timestamp}</span>
            },
        },
        {
            title: 'Duration (ms)',
            dataIndex: 'execution_time',
            width: 120,
            render: function Duration(_, item) {
                return <span className="font-mono">{Math.round(item.execution_time)}</span>
            },
        },
        {
            title: 'Team ID',
            dataIndex: 'team_id',
            width: 80,
        },
        {
            title: 'Experiment',
            dataIndex: 'experiment_name',
        },
        {
            title: 'Metric',
            dataIndex: 'experiment_metric_name',
        },
        {
            title: 'Path',
            width: 120,
            render: function Path(_, item) {
                if (!item.experiment_execution_path) {
                    return null
                }
                return (
                    <LemonTag type={item.experiment_execution_path === 'precomputed' ? 'success' : 'default'}>
                        {item.experiment_execution_path}
                    </LemonTag>
                )
            },
        },
        {
            title: 'Status',
            width: 80,
            render: function Status(_, item) {
                return item.exception ? (
                    <LemonTag type="danger">Error</LemonTag>
                ) : (
                    <LemonTag type="success">OK</LemonTag>
                )
            },
        },
    ]

    return (
        <SceneContent className="mt-4">
            <SceneTitleSection
                name="Query performance"
                description="Internal tooling for monitoring and managing query performance across all projects."
                resourceType={{
                    type: 'query_performance',
                    forceIcon: <IconDatabase />,
                }}
            />

            <h2 className="mt-4">Slowest experiment queries</h2>
            <div className="flex gap-2 mb-4 items-center">
                {TIME_RANGE_OPTIONS.map(({ label, hours }) => (
                    <LemonButton
                        key={hours}
                        type={hoursBack === hours ? 'primary' : 'tertiary'}
                        size="small"
                        onClick={() => setHoursBack(hours)}
                    >
                        {label}
                    </LemonButton>
                ))}
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={() => loadSlowestQueries()}
                    disabledReason={slowestQueriesLoading ? 'Loading...' : undefined}
                >
                    Refresh
                </LemonButton>
            </div>
            <LemonTable
                columns={slowestQueryColumns}
                dataSource={slowestQueries}
                loading={slowestQueriesLoading}
                emptyState="No experiment queries found in this time range"
                pagination={{ pageSize: 20 }}
                className="overflow-visible!"
                expandable={{
                    expandedRowRender: function ExpandedQuery(item) {
                        return (
                            <div className="p-2">
                                {item.exception && (
                                    <div className="mb-2 p-2 bg-danger-highlight rounded text-xs font-mono">
                                        {item.exception}
                                    </div>
                                )}
                                <CodeSnippet language={Language.SQL} thing="query" maxLinesWithoutExpansion={10}>
                                    {item.query}
                                </CodeSnippet>
                            </div>
                        )
                    },
                }}
            />

            <h2 className="mt-8">Experiment precomputation</h2>
            <LemonInput
                type="search"
                placeholder="Search by organization name..."
                value={search}
                onChange={setSearch}
                className="mb-4 max-w-md"
            />
            <LemonTable
                columns={precomputationColumns}
                dataSource={precomputationTeams}
                loading={precomputationTeamsLoading}
                emptyState={search ? 'No teams found' : 'No teams have precomputation enabled'}
            />
        </SceneContent>
    )
}
