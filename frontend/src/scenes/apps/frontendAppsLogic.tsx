import { actions, afterMount, kea, path } from 'kea'
import type { frontendAppsLogicType } from './frontendAppsLogicType'
import { getAppContext } from 'lib/utils/getAppContext'
import { organizationLogic } from 'scenes/organizationLogic'
import { loaders } from 'kea-loaders'
import { FrontendApp } from '~/types'
import { frontendAppRequire } from './frontendAppRequire'

/** Load frontend apps when PostHog launches, data from `appContext.frontend_apps`. */
export const frontendAppsLogic = kea<frontendAppsLogicType>([
    path(['scenes', 'frontendAppsLogic']),
    actions({ loadFrontendApp: (id: number) => ({ id }) }),
    loaders(({ values }) => ({
        frontendApps: [
            {} as Record<string, FrontendApp>,
            {
                loadFrontendApp: async ({ id }) => {
                    try {
                        const siteUrl = `http://localhost:8000`
                        const exports = await import(
                            `${siteUrl}/api/organizations/${organizationLogic.values.currentOrganization?.id}/plugins/${id}/frontend`
                        )
                        if ('getFrontendApp' in exports) {
                            const app = exports.getFrontendApp(frontendAppRequire)
                            if ('scene' in app) {
                                return { ...values.frontendApps, [id]: { ...app.scene, id } }
                            }
                            throw Error(`Could not find exported "scene" for plugin ${id}`)
                        }
                        throw Error(`Could not find exported "getFrontendApp" for plugin ${id}`)
                    } catch (error) {
                        console.error(`Can not load frontend for plugin ${id}`)
                        console.error(error)
                        throw error
                    }
                },
            },
        ],
    })),
    afterMount(({ actions }) => {
        const appContext = getAppContext()
        for (const id of appContext?.frontend_apps || []) {
            actions.loadFrontendApp(id)
        }
    }),
])
