import { useActions, useValues } from 'kea'

import { IconDatabase } from '@posthog/icons'

import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { SceneExport } from 'scenes/sceneTypes'
import { userLogic } from 'scenes/userLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { PrecomputationTeam, queryPerformanceLogic } from './queryPerformanceLogic'

export const scene: SceneExport = {
    component: QueryPerformance,
    logic: queryPerformanceLogic,
}

export function QueryPerformance(): JSX.Element {
    const { user } = useValues(userLogic)
    const { precomputationTeams, precomputationTeamsLoading, search } = useValues(queryPerformanceLogic)
    const { setSearch, setPrecomputation } = useActions(queryPerformanceLogic)

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

    const columns: LemonTableColumns<PrecomputationTeam> = [
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

    return (
        <SceneContent>
            <SceneTitleSection
                name="Query performance"
                description="Internal tooling for monitoring and managing query performance across all projects."
                resourceType={{
                    type: 'query_performance',
                    forceIcon: <IconDatabase />,
                }}
            />
            <h2 className="mt-4">Experiment precomputation</h2>
            <LemonInput
                type="search"
                placeholder="Search by organization name..."
                value={search}
                onChange={setSearch}
                className="mb-4 max-w-md"
            />
            <LemonTable
                columns={columns}
                dataSource={precomputationTeams}
                loading={precomputationTeamsLoading}
                emptyState={search ? 'No teams found' : 'No teams have precomputation enabled'}
            />
        </SceneContent>
    )
}
