import { useValues } from 'kea'

import { IconDatabase } from '@posthog/icons'

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
]

export function QueryPerformance(): JSX.Element {
    const { user } = useValues(userLogic)
    const { precomputationTeams, precomputationTeamsLoading } = useValues(queryPerformanceLogic)

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
            <h2 className="mt-4">Teams with precomputation enabled</h2>
            <LemonTable
                columns={precomputationColumns}
                dataSource={precomputationTeams}
                loading={precomputationTeamsLoading}
                emptyState="No teams have precomputation enabled"
            />
        </SceneContent>
    )
}
