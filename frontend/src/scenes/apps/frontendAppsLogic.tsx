import { actions, afterMount, connect, defaults, kea, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { getAppContext } from 'lib/utils/getAppContext'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { urls } from 'scenes/urls'

import { FrontendApp, FrontendAppConfig } from '~/types'

import { frontendAppRequire } from './frontendAppRequire'
import type { frontendAppsLogicType } from './frontendAppsLogicType'

/** Manages the loading and lifecycle of frontend apps. */
export const frontendAppsLogic = kea<frontendAppsLogicType>([
    path(['scenes', 'frontendAppsLogic']),
    connect({ values: [featureFlagLogic, ['featureFlags']] }),
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
                                pluginType: plugin?.plugin_type ?? null,
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
                            if (app.scene.onInit) {
                                window.setTimeout(() => app.scene.onInit(values.appConfigs[id]), 0)
                            }
                            return { ...values.frontendApps, [id]: { ...app.scene, id, pluginId } }
                        }
                        if ('no_frontend' in app || 'transpiling' in app) {
                            // Also retry with "no frontend". We will get this error when using a github/zip
                            // app, after it's saved in the db, but before loadPlugin runs the first time.
                            // Wait up to 2min.
                            const maxAttempts = 30
                            if (attempt < maxAttempts) {
                                window.setTimeout(
                                    () => actions.loadFrontendApp(id, pluginId, true, attempt + 1),
                                    1000 + Math.min(attempt, 10) * 300
                                )
                            } else {
                                lemonToast.error(`Timeout waiting for app ${id} to reload.`)
                            }
                            return values.frontendApps
                        }
                        if ('error' in app) {
                            lemonToast.error(`Cannot load frontend for app ${id}: ${app.error}`)
                            return values.frontendApps
                        }
                        throw Error(`Could not find exported "scene" or "error" for app ${id}`)
                    }
                    throw Error(`Could not find exported "getFrontendApp" for app ${id}`)
                } catch (error) {
                    console.error(`Cannot load frontend for app ${id}`)
                    console.error(error)
                    lemonToast.error(`Cannot load frontend for app ${id}: ${error}`)
                    throw error
                }
            },
        },
    })),
    reducers({
        frontendApps: {
            unloadFrontendApp: (frontendApps, { id }) => {
                const { [id]: _discard, ...rest } = frontendApps
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
