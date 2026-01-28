import { actions, connect, kea, path, props, reducers, selectors } from 'kea'
import { actionToUrl, router } from 'kea-router'

import { Scene } from 'scenes/sceneTypes'
import { settingsLogic } from 'scenes/settings/settingsLogic'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import { CUSTOMER_ANALYTICS_LOGIC_KEY } from '../../utils'
import type { customerAnalyticsConfigurationSceneLogicType } from './customerAnalyticsConfigurationSceneLogicType'

export type ConfigurationSceneTabType =
    | 'group-analytics'
    | 'customer-analytics-usage-metrics'
    | 'customer-analytics-dashboard-events'

export interface CustomerAnalyticsConfigurationSceneLogicProps {
    initialTab?: ConfigurationSceneTabType
}

export const customerAnalyticsConfigurationSceneLogic = kea<customerAnalyticsConfigurationSceneLogicType>([
    path(['scenes', 'customer-analytics', 'configuration', 'customerAnalyticsConfigurationSceneLogic']),
    props({} as CustomerAnalyticsConfigurationSceneLogicProps),

    connect(({ initialTab }: CustomerAnalyticsConfigurationSceneLogicProps) => ({
        actions: [
            settingsLogic({
                logicKey: CUSTOMER_ANALYTICS_LOGIC_KEY,
                sectionId: 'environment-customer-analytics',
                settingId: initialTab || 'customer-analytics-dashboard-events',
            }),
            ['selectSetting'],
        ],
    })),

    actions({
        setTab: (tab: ConfigurationSceneTabType) => ({ tab }),
    }),

    reducers(({ props }) => ({
        tab: [
            props.initialTab as ConfigurationSceneTabType,
            {
                setTab: (_, { tab }) => tab,
            },
        ],
    })),

    selectors({
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    key: Scene.CustomerAnalytics,
                    path: urls.customerAnalytics(),
                    name: 'Customer analytics',
                    iconType: 'cohort',
                },
                {
                    key: Scene.CustomerAnalyticsConfiguration,
                    path: urls.customerAnalyticsConfiguration(),
                    name: 'Configuration',
                    iconType: 'cohort',
                },
            ],
        ],
    }),

    actionToUrl({
        selectSetting: ({ setting }) => {
            const { currentLocation } = router.values

            return [
                currentLocation.pathname,
                { ...currentLocation.searchParams, tab: setting },
                currentLocation.hashParams,
            ]
        },
    }),
])
