import { BuiltLogic, connect, kea, key, LogicWrapper, path, props, selectors } from 'kea'
import { frontendAppsLogic } from 'scenes/apps/frontendAppsLogic'
import { FrontendApp } from '~/types'
import type { frontendAppSceneLogicType } from './frontendAppSceneLogicType'
import { subscriptions } from 'kea-subscriptions'
import { objectsEqual } from 'lib/utils'
import { urls } from 'scenes/urls'

export interface FrontendAppSceneLogicProps {
    /** Used as the logic's key */
    id: number
}

/** Logic responsible for loading the injected frontend scene */
export const frontendAppSceneLogic = kea<frontendAppSceneLogicType<FrontendAppSceneLogicProps>>([
    path(['scenes', 'plugins', 'Frontend']),
    connect({ values: [frontendAppsLogic, ['frontendApps', 'appConfigs']] }),
    props({} as FrontendAppSceneLogicProps),
    key((props) => props.id),
    selectors({
        frontendApp: [
            (s) => [s.frontendApps, (_, props) => props.id],
            (frontendApps, id): FrontendApp => frontendApps[id],
        ],
        appConfig: [
            (s) => [s.appConfigs, (_, props) => props.id],
            (appConfigs, id): Record<string, any> => appConfigs[id],
        ],
        logic: [(s) => [s.frontendApp], (frontendApp): LogicWrapper | undefined => frontendApp?.logic],
        logicProps: [
            (s) => [(_, props) => props.id, s.appConfig],
            (id, appConfig) => ({ id, url: urls.frontendApp(id), config: appConfig }),
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
    }),
    subscriptions(({ cache }) => ({
        builtLogic: (builtLogic: BuiltLogic) => {
            cache.unmount?.()
            cache.unmount = builtLogic?.mount()
        },
    })),
])
