import { useActions, useValues } from 'kea'

import { IconDatabase } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonTabs } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
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
        teamIdFilter,
        experimentIdFilter,
    } = useValues(queryPerformanceLogic)
    const { setSearch, setPrecomputation, setHoursBack, loadSlowestQueries, setTeamIdFilter, setExperimentIdFilter } =
        useActions(queryPerformanceLogic)

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
            render: function OrgCell(_, team) {
                return (
                    <div className="flex items-center gap-1">
                        <span>{team.organization_name || <span className="text-muted">Unknown</span>}</span>
                        {team.organization_arr != null && (
                            <LemonTag type="completion">ARR ${team.organization_arr.toLocaleString()}</LemonTag>
                        )}
                    </div>
                )
            },
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
                        onChange={(enabled) => {
                            if (!enabled) {
                                LemonDialog.open({
                                    title: 'Disable precomputation?',
                                    maxWidth: '30rem',
                                    description: `Are you sure you want to disable precomputation for ${
                                        team.team_name || `team ${team.team_id}`
                                    }? Experiment queries will fall back to on-demand execution and may become significantly slower.`,
                                    primaryButton: {
                                        status: 'danger',
                                        children: 'Disable precomputation',
                                        onClick: () => setPrecomputation(team.team_id, false),
                                    },
                                    secondaryButton: {
                                        children: 'Cancel',
                                    },
                                })
                                return
                            }
                            setPrecomputation(team.team_id, true)
                        }}
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
            title: 'Organization',
            render: function OrgCell(_, item) {
                return (
                    <div className="flex items-center gap-1">
                        <span>{item.organization_name || <span className="text-muted">Unknown</span>}</span>
                        {item.organization_arr != null && (
                            <LemonTag type="completion">ARR ${item.organization_arr.toLocaleString()}</LemonTag>
                        )}
                    </div>
                )
            },
        },
        {
            title: 'Team ID',
            dataIndex: 'team_id',
            width: 80,
        },
        {
            title: 'Experiment',
            render: function ExperimentCell(_, item) {
                if (!item.experiment_name) {
                    return <span className="text-muted">Unknown</span>
                }
                if (!item.experiment_id || !item.team_id) {
                    return <span className="truncate max-w-60">{item.experiment_name}</span>
                }
                return (
                    <Link
                        to={`/project/${item.team_id}/experiments/${item.experiment_id}`}
                        target="_blank"
                        className="truncate max-w-60"
                    >
                        {item.experiment_name}
                    </Link>
                )
            },
        },
        {
            title: 'Metric',
            render: function Metric(_, item) {
                return (
                    <div className="flex items-center gap-1">
                        <span>{item.experiment_metric_name}</span>
                        {item.experiment_metric_type && <LemonTag type="muted">{item.experiment_metric_type}</LemonTag>}
                    </div>
                )
            },
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
            render: function Status(_, item) {
                if (!item.exception) {
                    return <LemonTag type="success">OK</LemonTag>
                }
                const firstLine = item.exception.split('\n')[0]
                const preview = firstLine.length > 60 ? firstLine.slice(0, 60) + '…' : firstLine
                return (
                    <div className="flex items-center gap-1 min-w-0">
                        <LemonTag type="danger">Error</LemonTag>
                        <span className="font-mono text-xs text-danger truncate">{preview}</span>
                    </div>
                )
            },
        },
    ]

    return (
        <SceneContent className="mt-4 pb-8">
            <SceneTitleSection
                name="Query performance"
                description="Internal tooling for monitoring and managing query performance across all projects."
                resourceType={{
                    type: 'query_performance',
                    forceIcon: <IconDatabase />,
                }}
            />

            <LemonTabs
                activeKey="experiments"
                tabs={[
                    {
                        key: 'experiments',
                        label: 'Experiments',
                        content: (
                            <>
                                <h2>Slowest queries</h2>
                                <div className="flex flex-wrap gap-2 mb-4 items-center">
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
                                    <LemonInput
                                        type="number"
                                        min={1}
                                        size="small"
                                        placeholder="Team ID"
                                        value={teamIdFilter ? Number(teamIdFilter) : undefined}
                                        onChange={(value) => setTeamIdFilter(value != null ? String(value) : '')}
                                        className="w-32"
                                    />
                                    <LemonInput
                                        type="number"
                                        min={1}
                                        size="small"
                                        placeholder="Experiment ID"
                                        value={experimentIdFilter ? Number(experimentIdFilter) : undefined}
                                        onChange={(value) => setExperimentIdFilter(value != null ? String(value) : '')}
                                        className="w-36"
                                    />
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
                                    emptyState="No queries found in this time range"
                                    pagination={{ pageSize: 20 }}
                                    className="overflow-visible! flex-none!"
                                    expandable={{
                                        expandedRowRender: function ExpandedQuery(item) {
                                            return (
                                                <div className="p-2">
                                                    {item.exception && (
                                                        <div className="mb-2">
                                                            <CodeSnippet
                                                                language={Language.Text}
                                                                thing="error"
                                                                maxLinesWithoutExpansion={5}
                                                            >
                                                                {item.exception}
                                                            </CodeSnippet>
                                                        </div>
                                                    )}
                                                    <CodeSnippet
                                                        language={Language.SQL}
                                                        thing="query"
                                                        maxLinesWithoutExpansion={10}
                                                    >
                                                        {item.query}
                                                    </CodeSnippet>
                                                </div>
                                            )
                                        },
                                    }}
                                />

                                <h2 className="mt-8">Precomputation</h2>
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
                                    pagination={{ pageSize: 20 }}
                                    className="overflow-visible! flex-none!"
                                />
                            </>
                        ),
                    },
                ]}
            />
        </SceneContent>
    )
}
