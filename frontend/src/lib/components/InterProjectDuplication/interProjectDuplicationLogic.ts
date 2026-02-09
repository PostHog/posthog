import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'

import { TeamBasicType } from '~/types'

export interface InterProjectDuplicationRequest {
    resourceKind: string
    resourceId: string | number
    resourceName?: string
}

export interface CreatedResource {
    kind: string
    id: string
    team_id: number
}

export interface InterProjectDuplicationResponse {
    created_resources: CreatedResource[]
    count: number
}

export const interProjectDuplicationLogic = kea([
    path(['lib', 'components', 'InterProjectDuplication', 'interProjectDuplicationLogic']),
    connect(() => ({
        values: [organizationLogic, ['currentOrganization'], teamLogic, ['currentTeamId']],
    })),
    actions({
        openModal: (request: unknown) => ({ request: request as InterProjectDuplicationRequest }),
        closeModal: true,
        setDestinationTeamId: (teamId: unknown) => ({ teamId: teamId as number | null }),
    }),
    reducers({
        isModalOpen: [
            false,
            {
                openModal: () => true,
                closeModal: () => false,
            },
        ],
        request: [
            null as InterProjectDuplicationRequest | null,
            {
                openModal: (_, { request }) => request,
                closeModal: () => null,
            },
        ],
        destinationTeamId: [
            null as number | null,
            {
                openModal: () => null,
                closeModal: () => null,
                setDestinationTeamId: (_, { teamId }) => teamId,
            },
        ],
    }),
    selectors({
        teamOptions: [
            (s: any) => [s.currentOrganization, s.currentTeamId],
            (currentOrganization: any, currentTeamId: number | null) =>
                (currentOrganization?.teams ?? [])
                    .filter((team: TeamBasicType) => team.id !== currentTeamId)
                    .sort((a: TeamBasicType, b: TeamBasicType) => a.name.localeCompare(b.name))
                    .map((team: TeamBasicType) => ({ value: team.id, label: team.name })),
        ],
    }),
    loaders(({ values }) => ({
        duplicationResult: [
            null as InterProjectDuplicationResponse | null,
            {
                submitDuplication: async () => {
                    const { request, destinationTeamId, currentTeamId, currentOrganization } = values
                    if (!request || !destinationTeamId || !currentTeamId || !currentOrganization) {
                        throw new Error('Missing required fields for duplication')
                    }

                    return await api.create<InterProjectDuplicationResponse>(
                        `api/organizations/${currentOrganization.id}/resource_transfers/transfer/`,
                        {
                            source_team_id: currentTeamId,
                            destination_team_id: destinationTeamId,
                            resource_kind: request.resourceKind,
                            resource_id: String(request.resourceId),
                        }
                    )
                },
            },
        ],
    })),
    listeners(({ actions, values }) => ({
        submitDuplicationSuccess: () => {
            const resourceName = values.request?.resourceName || values.request?.resourceKind
            const destTeam = values.currentOrganization?.teams.find(
                (t: TeamBasicType) => t.id === values.destinationTeamId
            )
            const destName = destTeam?.name || 'the selected project'
            lemonToast.success(`${resourceName} copied to ${destName}`)
            actions.closeModal()
        },
        submitDuplicationFailure: ({ error }) => {
            lemonToast.error(`Failed to copy resource: ${error?.message || 'Unknown error'}`)
        },
    })),
])
