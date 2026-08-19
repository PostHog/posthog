import api from 'lib/api'

import { batchExportsList } from 'products/batch_exports/frontend/generated/api'
import type { BatchExportApi, PaginatedBatchExportListApi } from 'products/batch_exports/frontend/generated/api.schemas'
import { hogFunctionsList } from 'products/cdp/frontend/generated/api'
import type {
    HogFunctionMinimalApi,
    PaginatedHogFunctionMinimalListApi,
} from 'products/cdp/frontend/generated/api.schemas'

export type PipelineKind = 'destination' | 'transformation' | 'plugin' | 'batch_export'

export type PipelineItem = {
    id: string
    name: string
    kind: PipelineKind
    teamId: number
    teamName: string
}

export type PipelineTeam = {
    id: number
    name: string
}

export const PIPELINE_KIND_ORDER: PipelineKind[] = ['destination', 'transformation', 'batch_export', 'plugin']

export const PIPELINE_KIND_LABELS: Record<PipelineKind, string> = {
    destination: 'Destinations',
    transformation: 'Transformations',
    batch_export: 'Batch exports',
    plugin: 'Plugin destinations (deprecated)',
}

type PluginDestinationConfig = { id: number; name?: string | null }

function displayName(name: string | null | undefined): string {
    return name?.trim() || '(unnamed)'
}

export function comparePipelines(a: PipelineItem, b: PipelineItem): number {
    return PIPELINE_KIND_ORDER.indexOf(a.kind) - PIPELINE_KIND_ORDER.indexOf(b.kind) || a.name.localeCompare(b.name)
}

/**
 * Every pipeline in one project, with the IDs the notification settings use as keys.
 *
 * The ID shape has to match `PIPELINE_ID_PATTERN` in `posthog/api/user.py`, which is what the
 * backend accepts when a member or an admin writes a per-pipeline preference.
 *
 * Each source is fetched on its own, so a product that errors drops out of the list instead of
 * blanking the pipelines of the products that answered.
 */
export async function loadTeamPipelines(team: PipelineTeam): Promise<PipelineItem[]> {
    const items: PipelineItem[] = []

    try {
        const initial: PaginatedHogFunctionMinimalListApi = await hogFunctionsList(String(team.id), {
            type: ['destination', 'site_destination', 'transformation'],
            limit: 100,
        })
        const hogFunctions: HogFunctionMinimalApi[] = [
            ...initial.results,
            ...(await api.loadPaginatedResults<HogFunctionMinimalApi>(initial.next ?? null)),
        ]
        for (const hogFunction of hogFunctions) {
            items.push({
                id: `hog_function:${hogFunction.id}`,
                name: displayName(hogFunction.name),
                kind: hogFunction.type === 'transformation' ? 'transformation' : 'destination',
                teamId: team.id,
                teamName: team.name,
            })
        }
    } catch (e) {
        console.warn(`Failed to load hog functions for team ${team.id}`, e)
    }

    try {
        const pluginConfigs = await api.loadPaginatedResults<PluginDestinationConfig>(
            `api/projects/${team.id}/pipeline_destination_configs/?limit=100`
        )
        for (const pluginConfig of pluginConfigs) {
            items.push({
                id: `plugin_config:${pluginConfig.id}`,
                name: displayName(pluginConfig.name),
                kind: 'plugin',
                teamId: team.id,
                teamName: team.name,
            })
        }
    } catch (e) {
        console.warn(`Failed to load plugin destinations for team ${team.id}`, e)
    }

    try {
        const initial: PaginatedBatchExportListApi = await batchExportsList(String(team.id), { limit: 100 })
        const batchExports: BatchExportApi[] = [
            ...initial.results,
            ...(await api.loadPaginatedResults<BatchExportApi>(initial.next ?? null)),
        ]
        for (const batchExport of batchExports) {
            items.push({
                id: `batch_export:${batchExport.id}`,
                name: displayName(batchExport.name),
                kind: 'batch_export',
                teamId: team.id,
                teamName: team.name,
            })
        }
    } catch (e) {
        console.warn(`Failed to load batch exports for team ${team.id}`, e)
    }

    return items.sort(comparePipelines)
}
