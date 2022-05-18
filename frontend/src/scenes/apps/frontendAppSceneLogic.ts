import { actions, BuiltLogic, connect, kea, key, listeners, LogicWrapper, props, selectors, path } from 'kea'
import { frontendAppsLogic } from 'scenes/apps/frontendAppsLogic'
import { FrontendApp, FrontendAppConfig } from '~/types'
import type { frontendAppSceneLogicType } from './frontendAppSceneLogicType'
import { subscriptions } from 'kea-subscriptions'
import { objectsEqual } from 'lib/utils'
import { urls } from 'scenes/urls'
import { FrontendAppSceneLogicProps, FrontendAppSceneProps } from 'scenes/apps/types'
import api from 'lib/api'

/** Logic responsible for loading the injected frontend scene */
export const frontendAppSceneLogic = kea<frontendAppSceneLogicType>([
    path(['scenes', 'apps', 'frontendAppSceneLogic']),
    props({} as FrontendAppSceneLogicProps),
    key((props) => props.id),
    connect({
        actions: [frontendAppsLogic, ['setAppConfig']],
        values: [frontendAppsLogic, ['frontendApps', 'appConfigs']],
    }),
    actions({
        updateAppConfig: (appConfig: Record<string, any>, callback: (error?: any) => void) => ({ appConfig, callback }),
    }),
    listeners(({ values }) => ({
        updateAppConfig: async ({ appConfig, callback }) => {
            try {
                const { pluginConfigId } = values.appConfig
                await api.update(`api/plugin_config/${pluginConfigId}/`, { config: appConfig })
                callback()
            } catch (e) {
                callback(e)
            }
        },
    })),
    selectors(({ actions }) => ({
        frontendApp: [
            (s) => [s.frontendApps, (_, props) => props.id],
            (frontendApps, id): FrontendApp => frontendApps[id],
        ],
        appConfig: [
            (s) => [s.appConfigs, (_, props) => props.id],
            (appConfigs, id): FrontendAppConfig => appConfigs[id],
        ],
        logic: [(s) => [s.frontendApp], (frontendApp): LogicWrapper | undefined => frontendApp?.logic],
        logicProps: [
            (s) => [s.appConfig],
            (appConfig): FrontendAppSceneProps => ({
                ...appConfig,
                name: appConfig.name,
                url: urls.frontendApp(appConfig.pluginConfigId),
                config: appConfig.config,
                setConfig: async (config: Record<string, any>) => {
                    return new Promise((resolve, reject) => {
                        actions.updateAppConfig(config, (error) => {
                            error ? reject(error) : resolve()
                        })
                    })
                },
            }),
        ],
        builtLogic: [(s) => [s.logic, s.logicProps], (logic: any, props: any) => logic?.(props)],
        Component: [(s) => [s.frontendApp], (frontendApp: any) => frontendApp?.component],
        breadcrumbsSelector: [(s) => [s.builtLogic], (builtLogic) => builtLogic?.selectors.breadcrumbs],
        breadcrumbs: [
            (s) => [(state, props) => s.breadcrumbsSelector(state, props)?.(state, props), s.frontendApp],
            (breadcrumbs, frontendApp: FrontendApp) => {
                return (
                    breadcrumbs ?? [
                        {
                            name: frontendApp?.title || `App #${frontendApp?.id}`,
                        },
                    ]
                )
            },
            { resultEqualityCheck: objectsEqual },
        ],
    })),
    subscriptions(({ cache }) => ({
        builtLogic: (builtLogic: BuiltLogic) => {
            cache.unmount?.()
            cache.unmount = builtLogic?.mount()
        },
    })),
])
