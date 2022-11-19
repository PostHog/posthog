import { actions, afterMount, connect, kea, listeners, path } from 'kea'

import type { dashboardTemplateLogicType } from './dashboardTemplateLogicType'
import { loaders } from 'kea-loaders'
import {
    DashboardTemplateListing,
    DashboardTemplateRefresh,
    DashboardTemplateScope,
    DashboardType,
    FilterType,
    Tileable,
} from '~/types'
import api from 'lib/api'
import { lemonToast } from 'lib/components/lemonToast'
import { prompt } from 'lib/logic/prompt'
import { teamLogic } from 'scenes/teamLogic'
import posthog from 'posthog-js'
import { delay } from 'lib/utils'
import { Spinner } from 'lib/components/Spinner/Spinner'
import { Animation } from 'lib/components/Animation/Animation'
import { AnimationType } from 'lib/animations/animations'
import { DelayedContent } from 'lib/components/DelayedContent/DelayedContent'

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

export async function pollTemplateRefreshStatus(task_id: string): Promise<void> {
    const poller = new Promise(async (resolve, reject) => {
        const startTime = performance.now()

        try {
            let attempts = 0
            let dashboardTemplateRefresh: DashboardTemplateRefresh = await api.dashboardTemplates.templateRefreshStatus(
                task_id
            )
            const maxPoll = 30000
            while (attempts < maxPoll) {
                attempts++

                if (dashboardTemplateRefresh?.task_status === 'SUCCESS') {
                    const refreshPollingTime = performance.now() - startTime
                    posthog.capture('dashboard template refresh succeeded', { refreshPollingTime })

                    resolve('Template refresh complete')
                    return
                }

                dashboardTemplateRefresh = await api.dashboardTemplates.templateRefreshStatus(task_id)
                await delay(maxPoll / 10)
            }

            reject('Content not loaded in time...')
        } catch (e: any) {
            const refreshPollingTime = performance.now() - startTime
            posthog.capture('dashboard template refresh failed', { refreshPollingTime })
            reject(`Template refresh failed: ${JSON.stringify(e)}`)
        }
    })
    await lemonToast.promise(
        poller,
        {
            pending: (
                <DelayedContent atStart="Template refresh queued..." afterDelay="Waiting for template refresh..." />
            ),
            success: 'Template refresh complete!',
            error: 'Template refresh failed!',
        },
        {
            pending: (
                <DelayedContent
                    atStart={<Spinner />}
                    afterDelay={<Animation size="small" type={AnimationType.SportsHog} />}
                />
            ),
        }
    )
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
    connect({
        logic: [prompt({ key: 'rename-dashboard-template' })],
    }),
    actions({
        renameDashboardTemplate: (id: string, currentName: string) => ({ id, currentName }),
    }),
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
                    templateScope,
                }: {
                    templateName: string
                    dashboard: DashboardType
                    templateScope: DashboardTemplateScope
                }) => {
                    return await api.dashboardTemplates.create({
                        template_name: templateName,
                        source_dashboard: dashboard.id,
                        ...templateFrom(dashboard),
                        scope: templateScope,
                    })
                },
                importDashboardTemplate: async ({ templateJson }: { templateJson: File }) => {
                    return await api.dashboardTemplates.create(JSON.parse(await templateJson.text()))
                },
                deleteDashboardTemplate: async (id: string) => {
                    await api.dashboardTemplates.softDelete(id)
                    return null
                },
            },
        ],
    }),
    listeners(({ actions }) => ({
        saveDashboardTemplateSuccess: () => {
            lemonToast.success('Template saved successfully')
            actions.getAllDashboardTemplates()
        },
        deleteDashboardTemplateSuccess: () => {
            lemonToast.success('Template deleted successfully')
            actions.getAllDashboardTemplates()
        },
        renameDashboardTemplate: async ({ id, currentName }) => {
            prompt({ key: 'rename-dashboard-template' }).actions.prompt({
                title: 'Rename template',
                placeholder: 'Please enter the new name',
                value: currentName,
                error: 'You must enter a template name',
                success: async (name: string) => {
                    await api.update(
                        `api/projects/${teamLogic.values.currentTeamId}/dashboard_templates/${id}?basic=true`,
                        {
                            template_name: name,
                        }
                    )
                    lemonToast.success(
                        <>
                            Renamed template from <b>{currentName}</b> to <b>{name}</b>
                        </>
                    )
                    actions.getAllDashboardTemplates()
                },
            })
        },
    })),
    afterMount(({ actions }) => {
        actions.getAllDashboardTemplates()
    }),
])
