import { actions, afterMount, defaults, kea, path, reducers } from 'kea'
import type { frontendAppsLogicType } from './frontendAppsLogicType'
import { getAppContext } from 'lib/utils/getAppContext'
import { loaders } from 'kea-loaders'
import { FrontendApp, FrontendAppConfig } from '~/types'
import { frontendAppRequire } from './frontendAppRequire'
import { lemonToast } from 'lib/components/lemonToast'

/** Load frontend apps when PostHog launches, data from `appContext.frontend_apps`. */
export const frontendAppsLogic = kea<frontendAppsLogicType>([
    path(['scenes', 'frontendAppsLogic']),
    actions({
        loadFrontendApp: (id: number, pluginId: number, reload: boolean = false) => ({ id, pluginId, reload }),
        unloadFrontendApp: (id: number) => ({ id }),
        setAppConfig: (id: number, appConfig: FrontendAppConfig) => ({ id, appConfig }),
        setAppConfigs: (appConfigs: Record<string, FrontendAppConfig>) => ({ appConfigs }),
    }),
    defaults({
        frontendApps: {} as Record<string, FrontendApp>,
    }),
    loaders(({ actions, values }) => ({
        frontendApps: {
            loadFrontendApp: async ({ id, pluginId, reload }) => {
                try {
                    const siteUrl = location.origin
                    const exports = await import(
                        `${siteUrl}/api/plugin_config/${id}/frontend${reload ? '?_=' + new Date().valueOf() : ''}`
                    )
                    if ('getFrontendApp' in exports) {
                        const app = exports.getFrontendApp(frontendAppRequire)
                        if ('scene' in app) {
                            return { ...values.frontendApps, [id]: { ...app.scene, id, pluginId } }
                        }
                        if ('transpiling' in app) {
                            window.setTimeout(() => actions.loadFrontendApp(id, pluginId, true), 1000)
                            return values.frontendApps
                        }
                        if ('error' in app) {
                            lemonToast.error(`Can not load frontend for plugin ${id}: ${app.error}`)
                            return values.frontendApps
                        }
                        throw Error(`Could not find exported "scene" or "error" for plugin ${id}`)
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
                // eslint-disable-next-line
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
            for (const { pluginId, pluginConfigId } of Object.values(appConfigs)) {
                actions.loadFrontendApp(pluginConfigId, pluginId)
            }
        }
    }),
])
