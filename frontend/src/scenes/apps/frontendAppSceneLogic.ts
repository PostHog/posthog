import { BuiltLogic, connect, kea, key, LogicWrapper, props, selectors, path } from 'kea'
import { frontendAppsLogic } from 'scenes/apps/frontendAppsLogic'
import { Breadcrumb, FrontendApp, FrontendAppConfig } from '~/types'
import type { frontendAppSceneLogicType } from './frontendAppSceneLogicType'
import { subscriptions } from 'kea-subscriptions'
import { objectsEqual } from 'lib/utils'

export interface FrontendAppSceneLogicProps {
    /** Used as the logic's key */
    id: number
}

/** Logic responsible for loading the injected frontend scene */
export const frontendAppSceneLogic = kea<frontendAppSceneLogicType>([
    path(['scenes', 'apps', 'frontendAppSceneLogic']),
    props({} as FrontendAppSceneLogicProps),
    key((props) => props.id),
    connect({
        values: [frontendAppsLogic, ['frontendApps', 'appConfigs']],
    }),
    selectors(() => ({
        // Frontend app created after receiving a bundle via import('').getFrontendApp()
        frontendApp: [
            (s) => [s.frontendApps, (_, props) => props.id],
            (frontendApps, id): FrontendApp | undefined => frontendApps[id],
        ],
        // Config passed to app component and logic as props. Sent in Django's app context.
        appConfig: [
            (s) => [s.appConfigs, (_, props) => props.id],
            (appConfigs, id): FrontendAppConfig | undefined => appConfigs[id],
        ],
        logic: [(s) => [s.frontendApp], (frontendApp): LogicWrapper | undefined => frontendApp?.logic],
        builtLogic: [(s) => [s.logic, s.appConfig], (logic: any, props: any) => (logic && props ? logic(props) : null)],
        Component: [(s) => [s.frontendApp], (frontendApp: any) => frontendApp?.component],
        breadcrumbsSelector: [(s) => [s.builtLogic], (builtLogic) => builtLogic?.selectors.breadcrumbs],
        breadcrumbs: [
            (s) => [
                (state, props) => s.breadcrumbsSelector(state, props)?.(state, props),
                s.frontendApp,
                (_, props) => props.id,
            ],
            (breadcrumbs, frontendApp: FrontendApp, id): Breadcrumb[] => {
                return (
                    breadcrumbs ?? [
                        {
                            name: frontendApp
                                ? frontendApp?.title || `App #${frontendApp?.id ?? id}`
                                : `Loading app...`,
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
