import { actions, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import type { productLayoutLogicType } from './productLayoutLogicType'
import { breadcrumbsLogic } from '../Breadcrumbs/breadcrumbsLogic'
import { actionToUrl, router, urlToAction } from 'kea-router'

export interface ProductLayoutTopbarTab {
    key: string
    label: string
    url: string
    content?: React.ReactNode
    buttons?: React.ReactNode
    featureFlag?: keyof typeof FEATURE_FLAGS
    default?: boolean
    isNew?: boolean
}

export interface ProductLayoutConfig {
    baseUrl: string
    baseTabs: ProductLayoutTopbarTab[]
}

export interface TopbarTabKey {
    key: string
}

export const productLayoutLogic = kea<productLayoutLogicType>([
    path(() => ['layout', 'navigation', 'TopBar', 'productLayoutLogic']),
    connect(() => ({
        values: [breadcrumbsLogic, ['productLayoutTabs', 'productLayoutTabConfig', 'productBaseUrl']],
    })),
    actions({
        // setActiveTopBarTab: (tab: TopbarTabKey) => ({ tab }),
        setProductLayoutConfig: (config: ProductLayoutConfig) => ({ config }),
        setTab: (tab: string) => ({ tab }),
    }),
])
