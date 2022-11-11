import { afterMount, kea, listeners, path } from 'kea'

import type { dashboardTemplateLogicType } from './dashboardTemplateLogicType'
import { loaders } from 'kea-loaders'
import { DashboardTemplateListing, DashboardType, FilterType, Tileable } from '~/types'
import api from 'lib/api'
import { lemonToast } from 'lib/components/lemonToast'

type TextTilePayload = {
    type: 'TEXT'
    body: string
} & Tileable

type InsightTilePayload = {
    type: 'INSIGHT'
    name: string
    description: string
    filters: Partial<FilterType>
} & Tileable

type TilePayload = InsightTilePayload | TextTilePayload

export interface DashboardTemplateRequest {
    dashboard_name: string
    dashboard_description: string
    tags: string[]
    tiles: TilePayload[]
}

const templateFrom = (dashboard: DashboardType): DashboardTemplateRequest => ({
    dashboard_name: dashboard.name,
    dashboard_description: dashboard.description || '',
    tags: dashboard.tags || [],
    tiles: dashboard.tiles.map((tile) => {
        if (!!tile.text) {
            return {
                type: 'TEXT',
                body: tile.text.body,
                layouts: tile.layouts,
                color: tile.color,
            }
        }
        if (!!tile.insight) {
            return {
                type: 'INSIGHT',
                name: tile.insight.name,
                description: tile.insight.description || '',
                filters: tile.insight.filters,
                layouts: tile.layouts,
                color: tile.color,
            }
        }
        throw new Error('Unknown tile type')
    }),
})

export const dashboardTemplateLogic = kea<dashboardTemplateLogicType>([
    path(['scenes', 'dashboard', 'dashboardTemplates', 'dashboardTemplateLogic']),
    loaders({
        dashboardTemplates: [
            [] as DashboardTemplateListing[],
            {
                getAllDashboardTemplates: async () => {
                    const response = await api.dashboardTemplates.list()
                    return response.results || []
                },
            },
        ],
        dashboardTemplate: [
            null,
            {
                saveDashboardTemplate: async ({
                    templateName,
                    dashboard,
                }: {
                    templateName: string
                    dashboard: DashboardType
                }) => {
                    return await api.dashboardTemplates.create({
                        template_name: templateName,
                        source_dashboard: dashboard.id,
                        ...templateFrom(dashboard),
                    })
                },
            },
        ],
    }),
    listeners(() => ({
        saveDashboardTemplateSuccess: () => {
            lemonToast.success('Template saved successfully')
        },
    })),
    afterMount(({ actions }) => {
        actions.getAllDashboardTemplates()
    }),
])
