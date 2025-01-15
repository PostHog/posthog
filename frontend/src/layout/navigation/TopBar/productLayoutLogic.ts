import { actions, connect, kea, path } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'

import { breadcrumbsLogic } from '../Breadcrumbs/breadcrumbsLogic'
import type { productLayoutLogicType } from './productLayoutLogicType'

export interface ProductLayoutTopbarTab {
    key: string
    label: string
    url: string
    content?: React.ReactNode
    buttons?: React.ReactNode
    featureFlag?: keyof typeof FEATURE_FLAGS
    default?: boolean
    active?: boolean
    isNew?: boolean
}

export interface ProductLayoutConfig {
    baseUrl: string
    baseTabs: ProductLayoutTopbarTab[]
}

export const productLayoutLogic = kea<productLayoutLogicType>([
    path(() => ['layout', 'navigation', 'TopBar', 'productLayoutLogic']),
    connect(() => ({
        values: [breadcrumbsLogic, ['productLayoutConfig']],
    })),
    actions({}),
])
