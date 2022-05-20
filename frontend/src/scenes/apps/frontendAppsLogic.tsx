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
        loadFrontendApp: (id: number, pluginId: number, reload: boolean = false, attempt: number = 1) => ({
            id,
            pluginId,
            reload,
            attempt,
        }),
        unloadFrontendApp: (id: number) => ({ id }),
        setAppConfigs: (appConfigs: Record<string, FrontendAppConfig>) => ({ appConfigs }),
    }),
    defaults({
        frontendApps: {} as Record<string, FrontendApp>,
    }),
    loaders(({ actions, values }) => ({
        frontendApps: {
            loadFrontendApp: async ({ id, pluginId, reload, attempt }) => {
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
                        if ('no_frontend' in app || 'transpiling' in app) {
                            // Also retry with "no frontend". We will get this error when using a github/zip
                            // plugin, after it's saved in the db, but before loadPlugin runs the first time.
                            const maxAttempts = 5
                            if (attempt < maxAttempts) {
                                window.setTimeout(
                                    () => actions.loadFrontendApp(id, pluginId, true, attempt + 1),
                                    1000 + attempt * 300
                                )
                            }
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
