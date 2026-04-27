import { afterMount, connect, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'

import api from 'lib/api'
import { organizationLogic } from 'scenes/organizationLogic'
import { userLogic } from 'scenes/userLogic'

import type { OrganizationType, UserType } from '~/types'

import { batchExportsList } from 'products/batch_exports/frontend/generated/api'
import type { BatchExportApi, PaginatedBatchExportListApi } from 'products/batch_exports/frontend/generated/api.schemas'
import { hogFunctionsList } from 'products/cdp/frontend/generated/api'
import type {
    HogFunctionMinimalApi,
    PaginatedHogFunctionMinimalListApi,
} from 'products/cdp/frontend/generated/api.schemas'

import type { pipelineNotificationsLogicType } from './pipelineNotificationsLogicType'

export type PipelineKind = 'destination' | 'transformation' | 'plugin' | 'batch_export'

export type PipelineItem = {
    id: string
    name: string
    kind: PipelineKind
    teamId: number
    teamName: string
}

export type PipelineTeamGroup = {
    teamId: number
    teamName: string
    items: PipelineItem[]
}

export const PIPELINE_KIND_ORDER: PipelineKind[] = ['destination', 'transformation', 'batch_export', 'plugin']

export const PIPELINE_KIND_LABELS: Record<PipelineKind, string> = {
    destination: 'Destinations',
    transformation: 'Transformations',
    batch_export: 'Batch exports',
    plugin: 'Plugin destinations (deprecated)',
}

type PaginatedLike<T> = { next?: string | null; results: T[] }

type PluginDestinationConfig = { id: number; name?: string | null }

async function fetchAllPages<T>(initial: PaginatedLike<T>): Promise<T[]> {
    let all: T[] = [...initial.results]
    let next = initial.next
    while (next) {
        const page: PaginatedLike<T> = await api.get(next)
        all = all.concat(page.results)
        next = page.next
    }
    return all
}

function displayName(name: string | null | undefined): string {
    return name?.trim() || '(unnamed)'
}

export const pipelineNotificationsLogic = kea<pipelineNotificationsLogicType>([
    path(['scenes', 'settings', 'user', 'pipelineNotificationsLogic']),
    connect(() => ({
        values: [organizationLogic, ['currentOrganization'], userLogic, ['user']],
    })),
    loaders(({ values }) => ({
        pipelines: [
            [] as PipelineItem[],
            {
                loadPipelines: async () => {
                    const org: OrganizationType | null = values.currentOrganization
                    if (!org?.teams?.length) {
                        return []
                    }

                    const teamNamesById = new Map(org.teams.map((t) => [t.id, t.name]))

                    const perTeamItems = await Promise.all(
                        org.teams.map(async (team): Promise<PipelineItem[]> => {
                            const items: PipelineItem[] = []
                            try {
                                const initial: PaginatedHogFunctionMinimalListApi = await hogFunctionsList(
                                    String(team.id),
                                    {
                                        type: ['destination', 'site_destination', 'transformation'],
                                        limit: 100,
                                    }
                                )
                                const hfs = await fetchAllPages<HogFunctionMinimalApi>(initial)
                                for (const hf of hfs) {
                                    items.push({
                                        id: `hog_function:${hf.id}`,
                                        name: displayName(hf.name),
                                        kind: hf.type === 'transformation' ? 'transformation' : 'destination',
                                        teamId: team.id,
                                        teamName: team.name,
                                    })
                                }
                            } catch (e) {
                                console.warn(`Failed to load hog functions for team ${team.id}`, e)
                            }
                            try {
                                const initial: PaginatedLike<PluginDestinationConfig> = await api.get(
                                    `api/projects/${team.id}/pipeline_destination_configs/?limit=100`
                                )
                                const pcs = await fetchAllPages<PluginDestinationConfig>(initial)
                                for (const pc of pcs) {
                                    items.push({
                                        id: `plugin_config:${pc.id}`,
                                        name: displayName(pc.name),
                                        kind: 'plugin',
                                        teamId: team.id,
                                        teamName: team.name,
                                    })
                                }
                            } catch (e) {
                                console.warn(`Failed to load plugin destinations for team ${team.id}`, e)
                            }
                            return items
                        })
                    )

                    let batchExportItems: PipelineItem[] = []
                    try {
                        const initial: PaginatedBatchExportListApi = await batchExportsList(org.id, { limit: 100 })
                        const bes = await fetchAllPages<BatchExportApi>(initial)
                        batchExportItems = bes.map<PipelineItem>((be) => ({
                            id: `batch_export:${be.id}`,
                            name: displayName(be.name),
                            kind: 'batch_export',
                            teamId: be.team_id,
                            teamName: teamNamesById.get(be.team_id) ?? '',
                        }))
                    } catch (e) {
                        console.warn('Failed to load batch exports', e)
                    }

                    const items = [...perTeamItems.flat(), ...batchExportItems]
                    return items.sort(
                        (a, b) =>
                            a.teamName.localeCompare(b.teamName) ||
                            PIPELINE_KIND_ORDER.indexOf(a.kind) - PIPELINE_KIND_ORDER.indexOf(b.kind) ||
                            a.name.localeCompare(b.name)
                    )
                },
            },
        ],
    })),
    selectors({
        allPipelineIds: [(s) => [s.pipelines], (pipelines: PipelineItem[]): string[] => pipelines.map((p) => p.id)],
        pipelinesByTeam: [
            (s) => [s.pipelines],
            (pipelines: PipelineItem[]): Record<string, PipelineTeamGroup> =>
                pipelines.reduce(
                    (acc, pipeline) => {
                        const teamKey = `${pipeline.teamId}`
                        if (!acc[teamKey]) {
                            acc[teamKey] = {
                                teamId: pipeline.teamId,
                                teamName: pipeline.teamName,
                                items: [],
                            }
                        }
                        acc[teamKey].items.push(pipeline)
                        return acc
                    },
                    {} as Record<string, PipelineTeamGroup>
                ),
        ],
        isPipelineDisabled: [
            (s) => [s.user],
            (user: UserType | null) =>
                (pipelineId: string): boolean =>
                    !!user?.notification_settings?.pipeline_notifications_disabled?.[pipelineId],
        ],
    }),
    subscriptions(({ actions }) => ({
        currentOrganization: (curr: OrganizationType | null, prev: OrganizationType | null | undefined) => {
            if (curr?.id && curr.id !== prev?.id) {
                actions.loadPipelines()
            }
        },
    })),
    afterMount(({ actions, values }) => {
        if (values.currentOrganization?.teams?.length) {
            actions.loadPipelines()
        }
    }),
])
