import { BuiltLogic, connect, kea, key, LogicWrapper, path, props, selectors } from 'kea'
import { frontendAppsLogic } from 'scenes/apps/frontendAppsLogic'
import { FrontendApp } from '~/types'
import type { frontendAppSceneLogicType } from './frontendAppSceneLogicType'
import { subscriptions } from 'kea-subscriptions'
import { objectsEqual } from 'lib/utils'

export interface FrontendAppSceneLogicProps {
    /** Used as the logic's key */
    id: number
}

/** Logic responsible for loading the injected frontend scene */
export const frontendAppSceneLogic = kea<frontendAppSceneLogicType<FrontendAppSceneLogicProps>>([
    path(['scenes', 'plugins', 'Frontend']),
    connect([frontendAppsLogic]),
    props({} as FrontendAppSceneLogicProps),
    key((props) => props.id),
    selectors({
        frontendApp: [
            () => [frontendAppsLogic.selectors.frontendApps, (_, props) => props.id],
            (apps, id): FrontendApp => apps[id],
        ],
        logic: [(s) => [s.frontendApp], (frontendApp): LogicWrapper | undefined => frontendApp?.logic],
        builtLogic: [(s) => [s.logic, (_, props) => props], (logic: any, props: any) => logic?.(props)],
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
