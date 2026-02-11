import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'

import { TeamBasicType } from '~/types'

import type { resourceTransferLogicType } from './resourceTransferLogicType'

export interface ResourceTransferLogicProps {
    resourceKind: string
    resourceId: string
}

export interface PreviewResource {
    resource_kind: string
    resource_id: string
    display_name: string
    friendly_kind: string
    user_facing: boolean
    suggested_substitution?: {
        resource_kind: string
        resource_id: string
        display_name: string
    }
}

export interface PreviewResponse {
    resources: PreviewResource[]
}

export interface SearchResult {
    resource_kind: string
    resource_id: string
    display_name: string
}

export interface SearchResponse {
    results: SearchResult[]
}

export type SubstitutionChoice =
    | { mode: 'copy' }
    | { mode: 'substitute'; resource_kind: string; resource_id: string; display_name: string }

export interface CreatedResource {
    kind: string
    id: string
    team_id: number
}

export interface TransferResponse {
    created_resources: CreatedResource[]
    count: number
}

export const resourceTransferLogic = kea<resourceTransferLogicType>([
    path(['scenes', 'resource-transfer', 'resourceTransferLogic']),
    props({} as ResourceTransferLogicProps),
    key((props) => `${props.resourceKind}:${props.resourceId}`),
    connect(() => ({
        values: [organizationLogic, ['currentOrganization'], teamLogic, ['currentTeamId']],
    })),
    actions({
        setDestinationTeamId: (teamId: unknown) => ({ teamId: teamId as number | null }),
        setSubstitutionChoice: (resourceKey: string, choice: unknown) => ({
            resourceKey,
            choice: choice as SubstitutionChoice,
        }),
        searchResources: (resourceKind: string, query: string) => ({ resourceKind, query }),
        initializeSubstitutionChoices: (choices: Record<string, SubstitutionChoice>) => ({ choices }),
    }),
    reducers({
        destinationTeamId: [
            null as number | null,
            {
                setDestinationTeamId: (_, { teamId }) => teamId,
            },
        ],
        substitutionChoices: [
            {} as Record<string, SubstitutionChoice>,
            {
                setDestinationTeamId: () => ({}),
                setSubstitutionChoice: (state, { resourceKey, choice }) => ({
                    ...state,
                    [resourceKey]: choice,
                }),
                initializeSubstitutionChoices: (_, { choices }) => choices,
            },
        ],
    }),
    loaders(({ values, props: logicProps }) => ({
        preview: [
            null as PreviewResponse | null,
            {
                loadPreview: async () => {
                    const { destinationTeamId, currentTeamId, currentOrganization } = values
                    if (!destinationTeamId || !currentTeamId || !currentOrganization) {
                        throw new Error('Missing required fields for preview')
                    }

                    return await api.create<PreviewResponse>(
                        `api/organizations/${currentOrganization.id}/resource_transfers/preview/`,
                        {
                            source_team_id: currentTeamId,
                            destination_team_id: destinationTeamId,
                            resource_kind: logicProps.resourceKind,
                            resource_id: logicProps.resourceId,
                        }
                    )
                },
            },
        ],
        transferResult: [
            null as TransferResponse | null,
            {
                submitTransfer: async () => {
                    const { destinationTeamId, currentTeamId, currentOrganization, substitutionPayload } = values
                    if (!destinationTeamId || !currentTeamId || !currentOrganization) {
                        throw new Error('Missing required fields for transfer')
                    }

                    return await api.create<TransferResponse>(
                        `api/organizations/${currentOrganization.id}/resource_transfers/transfer/`,
                        {
                            source_team_id: currentTeamId,
                            destination_team_id: destinationTeamId,
                            resource_kind: logicProps.resourceKind,
                            resource_id: logicProps.resourceId,
                            substitutions: substitutionPayload,
                        }
                    )
                },
            },
        ],
        searchResults: [
            null as SearchResponse | null,
            {
                searchResources: async ({ resourceKind, query }) => {
                    const { destinationTeamId, currentOrganization } = values
                    if (!destinationTeamId || !currentOrganization) {
                        throw new Error('Missing required fields for search')
                    }

                    return await api.create<SearchResponse>(
                        `api/organizations/${currentOrganization.id}/resource_transfers/search/`,
                        {
                            team_id: destinationTeamId,
                            resource_kind: resourceKind,
                            q: query,
                        }
                    )
                },
            },
        ],
    })),
    selectors({
        teamOptions: [
            (s: any) => [s.currentOrganization, s.currentTeamId],
            (currentOrganization: any, currentTeamId: number | null) =>
                (currentOrganization?.teams ?? [])
                    .filter((team: TeamBasicType) => team.id !== currentTeamId)
                    .sort((a: TeamBasicType, b: TeamBasicType) => a.name.localeCompare(b.name))
                    .map((team: TeamBasicType) => ({ value: team.id, label: team.name })),
        ],
        rootResourceName: [
            (s: any, p: any) => [s.preview, p.resourceKind, p.resourceId],
            (preview: PreviewResponse | null, resourceKind: string, resourceId: string): string | null => {
                const root = preview?.resources.find(
                    (r) => r.resource_kind === resourceKind && r.resource_id === resourceId
                )
                return root?.display_name ?? null
            },
        ],
        userFacingResources: [
            (s: any, p: any) => [s.preview, p.resourceKind, p.resourceId],
            (preview: PreviewResponse | null, resourceKind: string, resourceId: string): PreviewResource[] =>
                preview?.resources.filter(
                    (r) => r.user_facing && !(r.resource_kind === resourceKind && r.resource_id === resourceId)
                ) ?? [],
        ],
        substitutionPayload: [
            (s: any) => [s.substitutionChoices],
            (
                choices: Record<string, SubstitutionChoice>
            ): {
                source_resource_kind: string
                source_resource_id: string
                destination_resource_kind: string
                destination_resource_id: string
            }[] =>
                Object.entries(choices)
                    .filter(
                        (entry): entry is [string, SubstitutionChoice & { mode: 'substitute' }] =>
                            entry[1].mode === 'substitute'
                    )
                    .map(([key, c]) => {
                        const [sourceKind, ...rest] = key.split(':')
                        const sourceId = rest.join(':')
                        return {
                            source_resource_kind: sourceKind,
                            source_resource_id: sourceId,
                            destination_resource_kind: c.resource_kind,
                            destination_resource_id: c.resource_id,
                        }
                    }),
        ],
    }),
    listeners(({ actions, values, props: logicProps }) => ({
        setDestinationTeamId: ({ teamId }) => {
            if (teamId) {
                actions.loadPreview()
            }
        },
        loadPreviewSuccess: ({ preview }) => {
            if (!preview) {
                return
            }
            const choices: Record<string, SubstitutionChoice> = {}
            for (const resource of preview.resources) {
                const key = `${resource.resource_kind}:${resource.resource_id}`
                const isRootResource =
                    resource.resource_kind === logicProps.resourceKind && resource.resource_id === logicProps.resourceId
                if (resource.user_facing && !isRootResource && resource.suggested_substitution) {
                    choices[key] = {
                        mode: 'substitute',
                        ...resource.suggested_substitution,
                    }
                } else {
                    choices[key] = { mode: 'copy' }
                }
            }
            actions.initializeSubstitutionChoices(choices)
        },
        submitTransferSuccess: () => {
            const destTeam = values.currentOrganization?.teams.find(
                (t: TeamBasicType) => t.id === values.destinationTeamId
            )
            const destName = destTeam?.name || 'the selected project'
            lemonToast.success(`Copied to ${destName}`)
            window.history.back()
        },
        submitTransferFailure: ({ error }) => {
            lemonToast.error(`Failed to copy resource: ${error}`)
        },
    })),
])
