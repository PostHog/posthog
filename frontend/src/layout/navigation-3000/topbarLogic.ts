import { actions, connect, kea, path, reducers, selectors } from 'kea'
import { actionToUrl } from 'kea-router'
import { FEATURE_FLAGS } from 'lib/constants'
import { sceneLogic } from 'scenes/sceneLogic'

import { breadcrumbsLogic } from '~/layout/navigation/Breadcrumbs/breadcrumbsLogic'

import type { topbarLogicType } from './topbarLogicType'

export interface TopbarTab {
    key: string
    label: string
    url: string
    content?: React.ReactNode
    buttons?: React.ReactNode
    featureFlag?: keyof typeof FEATURE_FLAGS
    default?: boolean
    isNew?: boolean
}

export const topbarLogic = kea<topbarLogicType>([
    path(() => ['scenes', 'navigation', 'topbar', 'topbarLogic']),
    connect(() => ({
        // actions: [sceneLogic, ['setScene']],
        values: [sceneLogic, ['activeScene', 'sceneConfig'], breadcrumbsLogic, ['productLayoutTabs']],
    })),
    actions({
        setTopBarTabs: (tabs: TopbarTab[]) => ({ tabs }),
        setActiveTopBarTab: (tab: TopbarTab) => ({ tab: tab.key }),
    }),
    reducers({
        // topBarTabs: [[] as TopbarTab[], {
        //     setTopBarTabs: (_, { tabs }) => tabs,
        // }],
        activeTopBarTab: [
            '' as string,
            {
                setActiveTopBarTab: (_, { tab }) => tab,
            },
        ],
    }),
    selectors(({ values }) => ({
        // breadcrumbs: [
        //     (s) => [s.activeTopBarTab],
        //     (tab: TopbarTab): Breadcrumb[] => {
        //         return [
        //             {
        //                 key: tab.key,
        //                 name: tab.label as string,
        //             },
        //         ]
        //     },
        // ],
        topBarTabs: [
            (s) => [s.activeScene, s.sceneConfig],
            (): TopbarTab[] => {
                return values.productLayoutTabs
            },
        ],
    })),
    actionToUrl(({ values }) => {
        return {
            setActiveTopBarTab: () => [values.activeTopBarTab],
        }
    }),
    // urlToAction(({ actions, values }) => ({
    //     '*': async (pathParams, _search, hashParams) => {
    //         const tab = values.tabConfigSelector(values.activeScene as string, values.sceneConfig as SceneConfig)
    //         console.log('tab', tab)
    //         // const tab = values.topBarTabs.find((tab) => tab.url === pathParams._)
    //         // console.log('tab', tab)
    //         // if (tab) {
    //         //     actions.setActiveTopBarTab(tab)
    //         // }
    //     },
    // })),

    // reducers({
    //     tabs: [[] as TopbarTab[], {
    //         setTabs: (_, { tabs }) => tabs,
    //     }],
    //     activeTab: [
    //         '' as string,
    //         {
    //             setActiveTab: (_, { tab }) => tab,
    //             setTabs: (_, { tabs }) => tabs.find((tab) => tab.default)?.key || tabs[0]?.key || '',
    //         },
    //     ],
    // }),

    // listeners(({ actions, values }) => ({
    //     setActiveTab: ({ key }) => {
    //         const tab = values.tabs.find((tab) => tab.key === key)

    //         if (tab?.isNew) {
    //             actions.hideNewBadge(tab.key)
    //         }
    //     },
    // })),

    // selectors({
    //     currentTab: [
    //         (s) => [s.tabs, s.activeTab],
    //         (tabs: TopbarTab[], activeTab: string): TopbarTab | null => {
    //             return tabs.find((tab) => tab.key === activeTab) || null
    //         },
    //     ],
    // }),

    // urlToAction(({ actions, values }) => ({
    //     '*': (_, __, ___, { pathname }) => {
    //         // First try to match based on exact URL
    //         const matchingTabByUrl = values.tabs.find((tab) => pathname === tab.url)
    //         if (matchingTabByUrl && matchingTabByUrl.key !== values.activeTab) {
    //             actions.setActiveTab(matchingTabByUrl.key)
    //             return
    //         }

    //         // Then try to match based on breadcrumbs
    //         const matchingTabByBreadcrumb = values.tabs.find((tab) =>
    //             values.breadcrumbs.some(breadcrumb =>
    //                 breadcrumb.key === tab.key ||
    //                 (breadcrumb.path && pathname.startsWith(breadcrumb.path))
    //             )
    //         )

    //         if (matchingTabByBreadcrumb && matchingTabByBreadcrumb.key !== values.activeTab) {
    //             actions.setActiveTab(matchingTabByBreadcrumb.key)
    //         }
    //     },
    // })),
])
