import { actions, afterMount, defaults, kea, path, reducers } from 'kea'
import type { frontendAppsLogicType } from './frontendAppsLogicType'
import { getAppContext } from 'lib/utils/getAppContext'
import { loaders } from 'kea-loaders'
import { FrontendApp, FrontendAppConfig } from '~/types'
import { frontendAppRequire } from './frontendAppRequire'
import { lemonToast } from 'lib/components/lemonToast'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { urls } from 'scenes/urls'

/** Manages the loading and lifecycle of frontend apps. */
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
        updateAppConfigs: (appConfigs: Record<string, FrontendAppConfig>) => ({ appConfigs }),
    }),
    defaults({
        frontendApps: {} as Record<string, FrontendApp>,
    }),
    loaders(({ actions, values }) => ({
        frontendApps: {
            loadFrontendApp: async ({ id, pluginId, reload, attempt }) => {
                if (!values.appConfigs[id]) {
                    if (pluginsLogic.findMounted()) {
                        const pluginConfig = Object.values(pluginsLogic.values.pluginConfigs).find((c) => c.id === id)
                        const plugin = pluginConfig ? pluginsLogic.values.plugins[pluginConfig.plugin] : undefined
                        if (!plugin && !pluginConfig) {
                            throw Error(`Could not load metadata for app with ID ${id}`)
                        }
                        actions.updateAppConfigs({
                            [id]: {
                                url: urls.frontendApp(id),
                                config: pluginConfig?.config ?? {},
                                pluginConfigId: id,
                                pluginId: pluginId,
                                name: plugin?.name ?? `App #${id}`,
                            },
                        })
                    }
                }
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
                updateAppConfigs: (state, { appConfigs }) => ({ ...state, ...appConfigs }),
            },
        ],
    }),
    afterMount(({ actions }) => {
        const appConfigs = getAppContext()?.frontend_apps || {}
        if (Object.keys(appConfigs).length > 0) {
            actions.updateAppConfigs(appConfigs)
            for (const { pluginId, pluginConfigId } of Object.values(appConfigs)) {
                actions.loadFrontendApp(pluginConfigId, pluginId)
            }
        }
    }),
])
