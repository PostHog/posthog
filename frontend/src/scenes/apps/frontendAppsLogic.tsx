import { actions, afterMount, defaults, kea, path, reducers } from 'kea'
import type { frontendAppsLogicType } from './frontendAppsLogicType'
import { getAppContext } from 'lib/utils/getAppContext'
import { organizationLogic } from 'scenes/organizationLogic'
import { loaders } from 'kea-loaders'
import { FrontendApp } from '~/types'
import { frontendAppRequire } from './frontendAppRequire'
import { lemonToast } from 'lib/components/lemonToast'

/** Load frontend apps when PostHog launches, data from `appContext.frontend_apps`. */
export const frontendAppsLogic = kea<frontendAppsLogicType>([
    path(['scenes', 'frontendAppsLogic']),
    actions({
        loadFrontendApp: (id: number, reload = false) => ({ id, reload }),
        unloadFrontendApp: (id: number) => ({ id }),
        setAppConfigs: (appConfigs: Record<string, Record<string, any>>) => ({ appConfigs }),
        setAppConfig: (id: number, appConfig: Record<string, any>) => ({ id, appConfig }),
    }),
    defaults({
        frontendApps: {} as Record<string, FrontendApp>,
    }),
    loaders(({ values }) => ({
        frontendApps: {
            loadFrontendApp: async ({ id, reload }) => {
                try {
                    const siteUrl = `http://localhost:8000`
                    const exports = await import(
                        `${siteUrl}/api/organizations/${
                            organizationLogic.values.currentOrganization?.id
                        }/plugins/${id}/frontend${reload ? '?_=' + new Date().valueOf() : ''}`
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
                    lemonToast.error(`Can not load frontend for plugin ${id}: ${error}`)
                    throw error
                }
            },
        },
    })),
    reducers({
        frontendApps: {
            unloadFrontendApp: (frontendApps, { id }) => {
                const { [id]: _removed, ...rest } = frontendApps
                return rest
            },
        },
        appConfigs: [
            {} as Record<string, Record<string, any>>,
            {
                setAppConfigs: (state, { appConfigs }) => ({ ...state, ...appConfigs }),
                setAppConfig: (state, { id, appConfig }) => ({ ...state, [id]: appConfig }),
            },
        ],
    }),
    afterMount(({ actions }) => {
        const appConfigs = getAppContext()?.frontend_apps || {}
        if (Object.keys(appConfigs).length > 0) {
            actions.setAppConfigs(appConfigs)
            for (const id of Object.keys(appConfigs)) {
                actions.loadFrontendApp(parseInt(id))
            }
        }
    }),
])
