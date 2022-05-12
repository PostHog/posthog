import { actions, afterMount, defaults, kea, path, reducers } from 'kea'
import type { frontendAppsLogicType } from './frontendAppsLogicType'
import { getAppContext } from 'lib/utils/getAppContext'
import { loaders } from 'kea-loaders'
import { FrontendApp } from '~/types'
import { frontendAppRequire } from './frontendAppRequire'
import { lemonToast } from 'lib/components/lemonToast'
import { FrontendAppConfig } from 'scenes/apps/types'

/** Load frontend apps when PostHog launches, data from `appContext.frontend_apps`. */
export const frontendAppsLogic = kea<frontendAppsLogicType>([
    path(['scenes', 'frontendAppsLogic']),
    actions({
        loadFrontendApp: (id: number, reload = false) => ({ id, reload }),
        unloadFrontendApp: (id: number) => ({ id }),
        setAppConfig: (id: number, appConfig: FrontendAppConfig) => ({ id, appConfig }),
        setAppConfigs: (appConfigs: Record<string, FrontendAppConfig>) => ({ appConfigs }),
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
                        `${siteUrl}/api/plugin_config/${id}/frontend${reload ? '?_=' + new Date().valueOf() : ''}`
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
            {} as Record<string, FrontendAppConfig>,
            {
                setAppConfigs: (state, { appConfigs }) => ({ ...state, ...appConfigs }),
                setAppConfig: (state, { id, appConfig }) => ({
                    ...state,
                    [id]: { ...(state[id] ?? {}), ...appConfig },
                }),
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
