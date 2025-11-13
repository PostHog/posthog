import { actions, connect, kea, path, reducers, selectors, useValues } from 'kea'
import { actionToUrl, combineUrl, router, urlToAction } from 'kea-router'
import React from 'react'

import { IconInfo } from '@posthog/icons'

import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { TitleWithIcon } from 'lib/components/TitleWithIcon'
import { FEATURE_FLAGS, FeatureFlagKey } from 'lib/constants'
import { LemonTab } from 'lib/lemon-ui/LemonTabs'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { capitalizeFirstLetter } from 'lib/utils'
import { Annotations } from 'scenes/annotations'
import { NewAnnotationButton } from 'scenes/annotations/AnnotationModal'
import { Comments } from 'scenes/data-management/comments/Comments'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { urls } from 'scenes/urls'
import { MarketingAnalyticsSettings } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/components/settings/MarketingAnalyticsSettings'

import { SIDE_PANEL_CONTEXT_KEY, SidePanelSceneContext } from '~/layout/navigation-3000/sidepanel/types'
import { ActivityScope, Breadcrumb } from '~/types'

import { ActionsTable } from 'products/actions/frontend/components/ActionsTable'
import { NewActionButton } from 'products/actions/frontend/components/NewActionButton'
import { RevenueAnalyticsSettings } from 'products/revenue_analytics/frontend/settings/RevenueAnalyticsSettings'

import type { dataManagementSceneLogicType } from './DataManagementSceneType'
import { EventDefinitionsTable } from './events/EventDefinitionsTable'
import { IngestionWarningsView } from './ingestion-warnings/IngestionWarningsView'
import { DataWarehouseManagedViewsetsScene } from './managed-viewsets/DataWarehouseManagedViewsetsScene'
import { PropertyDefinitionsTable } from './properties/PropertyDefinitionsTable'
import { SchemaManagement } from './schema/SchemaManagement'

export enum DataManagementTab {
    Actions = 'actions',
    EventDefinitions = 'events',
    PropertyDefinitions = 'properties',
    SchemaManagement = 'schema',
    Annotations = 'annotations',
    Comments = 'comments',
    History = 'history',
    IngestionWarnings = 'warnings',
    Revenue = 'revenue',
    MarketingAnalytics = 'marketing-analytics',
    DataWarehouseManagedViewsets = 'data-warehouse-managed-viewsets',
}

type TabConfig = {
    url: string
    label: LemonTab<any>['label']
    content: JSX.Element
    buttons?: React.ReactNode
    flag?: FeatureFlagKey
    tooltipDocLink?: string
    children?: {
        [path: string]: {
            component?: JSX.Element
        }
    }
}

const tabs: Record<DataManagementTab, TabConfig> = {
    [DataManagementTab.EventDefinitions]: {
        url: urls.eventDefinitions(),
        label: 'Event definitions',
        content: <EventDefinitionsTable />,
        tooltipDocLink: 'https://posthog.com/docs/data/events',
    },
    [DataManagementTab.Actions]: {
        url: urls.actions(),
        label: (
            <TitleWithIcon
                icon={
                    <Tooltip title="Actions consist of one or more events that you have decided to put into a deliberately-labeled bucket. They're used in insights and dashboards.">
                        <IconInfo />
                    </Tooltip>
                }
            >
                Actions
            </TitleWithIcon>
        ),
        buttons: <NewActionButton />,
        content: <ActionsTable />,
        tooltipDocLink: 'https://posthog.com/docs/data/actions',
    },
    [DataManagementTab.PropertyDefinitions]: {
        url: urls.propertyDefinitions(),
        label: (
            <TitleWithIcon
                icon={
                    <Tooltip title="Properties are additional data sent along with an event capture. Use properties to understand additional information about events and the actors that generate them.">
                        <IconInfo />
                    </Tooltip>
                }
            >
                Properties
            </TitleWithIcon>
        ),
        content: <PropertyDefinitionsTable />,
        tooltipDocLink: 'https://posthog.com/docs/new-to-posthog/understand-posthog#properties',
    },
    [DataManagementTab.SchemaManagement]: {
        url: urls.schemaManagement(),
        label: 'Property Groups',
        content: <SchemaManagement />,
        flag: FEATURE_FLAGS.SCHEMA_MANAGEMENT,
    },
    [DataManagementTab.Annotations]: {
        url: urls.annotations(),
        content: <Annotations />,
        label: 'Annotations',
        buttons: <NewAnnotationButton />,
        tooltipDocLink: 'https://posthog.com/docs/data/annotations',
        children: {
            [urls.annotation(':id')]: {},
        },
    },
    [DataManagementTab.Comments]: {
        url: urls.comments(),
        content: <Comments />,
        label: 'Comments',
        buttons: undefined,
        tooltipDocLink: 'https://posthog.com/docs/data/comments',
    },
    [DataManagementTab.History]: {
        url: urls.dataManagementHistory(),
        label: 'History',
        content: (
            <ActivityLog
                scope={ActivityScope.DATA_MANAGEMENT}
                caption="Only actions taken in the UI are captured in History. Automatic creation of definitions by ingestion is not shown here."
            />
        ),
        tooltipDocLink: 'https://posthog.com/docs/data#history',
    },
    [DataManagementTab.Revenue]: {
        url: urls.revenueSettings(),
        label: (
            <>
                Revenue{' '}
                <LemonTag type="warning" size="small" className="ml-2">
                    BETA
                </LemonTag>
            </>
        ),
        content: <RevenueAnalyticsSettings />,
    },
    [DataManagementTab.IngestionWarnings]: {
        url: urls.ingestionWarnings(),
        label: 'Ingestion warnings',
        content: <IngestionWarningsView />,
        flag: FEATURE_FLAGS.INGESTION_WARNINGS_ENABLED,
        tooltipDocLink: 'https://posthog.com/docs/data/ingestion-warnings',
    },
    [DataManagementTab.MarketingAnalytics]: {
        url: urls.marketingAnalytics(),
        label: (
            <>
                Marketing{' '}
                <LemonTag type="warning" size="small" className="ml-2">
                    BETA
                </LemonTag>
            </>
        ),
        content: <MarketingAnalyticsSettings />,
        flag: FEATURE_FLAGS.WEB_ANALYTICS_MARKETING,
    },
    [DataManagementTab.DataWarehouseManagedViewsets]: {
        url: urls.dataWarehouseManagedViewsets(),
        label: 'Managed viewsets',
        content: <DataWarehouseManagedViewsetsScene />,
        flag: FEATURE_FLAGS.MANAGED_VIEWSETS,
    },
}

const dataManagementSceneLogic = kea<dataManagementSceneLogicType>([
    path(['scenes', 'events', 'dataManagementSceneLogic']),
    connect(() => ({
        values: [featureFlagLogic, ['featureFlags']],
    })),
    actions({
        setTab: (tab: DataManagementTab) => ({ tab }),
    }),
    reducers({
        tab: [
            DataManagementTab.EventDefinitions as DataManagementTab,
            {
                setTab: (_, { tab }) => tab,
            },
        ],
    }),
    selectors({
        breadcrumbs: [
            (s) => [s.tab],
            (tab): Breadcrumb[] => {
                if (tab === DataManagementTab.EventDefinitions) {
                    return [
                        {
                            key: Scene.EventDefinition,
                            name: sceneConfigurations[Scene.EventDefinition].name,
                            path: urls.eventDefinitions(),
                            iconType: sceneConfigurations[Scene.EventDefinition].iconType || 'default_icon_type',
                        },
                    ]
                } else if (tab === DataManagementTab.Annotations) {
                    return [
                        {
                            key: Scene.Annotations,
                            name: sceneConfigurations[Scene.Annotations].name,
                            path: urls.annotations(),
                            iconType: sceneConfigurations[Scene.Annotations].iconType || 'default_icon_type',
                        },
                    ]
                } else if (tab === DataManagementTab.PropertyDefinitions) {
                    return [
                        {
                            key: Scene.PropertyDefinition,
                            name: sceneConfigurations[Scene.PropertyDefinition].name,
                            path: urls.propertyDefinitions(),
                            iconType: sceneConfigurations[Scene.PropertyDefinition].iconType || 'default_icon_type',
                        },
                    ]
                } else if (tab === DataManagementTab.Revenue) {
                    return [
                        {
                            key: Scene.RevenueAnalytics,
                            name: sceneConfigurations[Scene.RevenueAnalytics].name,
                            path: urls.revenueSettings(),
                            iconType: sceneConfigurations[Scene.RevenueAnalytics].iconType || 'default_icon_type',
                        },
                    ]
                } else if (tab === DataManagementTab.Comments) {
                    return [
                        {
                            key: Scene.Comments,
                            name: sceneConfigurations[Scene.Comments].name,
                            path: urls.comments(),
                            iconType: sceneConfigurations[Scene.Comments].iconType || 'default_icon_type',
                        },
                    ]
                } else if (tab === DataManagementTab.IngestionWarnings) {
                    return [
                        {
                            key: Scene.IngestionWarnings,
                            name: sceneConfigurations[Scene.IngestionWarnings].name,
                            path: urls.ingestionWarnings(),
                            iconType: sceneConfigurations[Scene.IngestionWarnings].iconType || 'default_icon_type',
                        },
                    ]
                } else if (tab === DataManagementTab.MarketingAnalytics) {
                    return [
                        {
                            key: Scene.WebAnalyticsMarketing,
                            name: sceneConfigurations[Scene.WebAnalyticsMarketing].name,
                            path: urls.marketingAnalytics(),
                            iconType: sceneConfigurations[Scene.WebAnalyticsMarketing].iconType || 'default_icon_type',
                        },
                    ]
                }
                return [
                    {
                        key: tab,
                        name: capitalizeFirstLetter(tab),
                        path: tabs[tab].url,
                        iconType: 'event_definition',
                    },
                ]
            },
        ],
        enabledTabs: [
            (s) => [s.featureFlags],
            (featureFlags): DataManagementTab[] => {
                const allTabs = Object.entries(tabs)

                return allTabs
                    .filter(([_, tab]) => {
                        return !tab.flag || !!featureFlags[tab.flag]
                    })
                    .map(([tabName, _]) => tabName) as DataManagementTab[]
            },
        ],
        [SIDE_PANEL_CONTEXT_KEY]: [
            (s) => [s.tab],
            (tab: DataManagementTab): SidePanelSceneContext | null => {
                const tabToScopeMap: Partial<Record<DataManagementTab, ActivityScope>> = {
                    [DataManagementTab.EventDefinitions]: ActivityScope.EVENT_DEFINITION,
                    [DataManagementTab.PropertyDefinitions]: ActivityScope.PROPERTY_DEFINITION,
                    [DataManagementTab.Actions]: ActivityScope.ACTION,
                }

                const currentScope = tabToScopeMap[tab]
                if (currentScope) {
                    return {
                        activity_scope: currentScope,
                    }
                }
                return null
            },
        ],
    }),
    actionToUrl(() => ({
        setTab: ({ tab }) => {
            const tabUrl = tabs[tab as DataManagementTab]?.url || tabs.events.url
            if (combineUrl(tabUrl).pathname === router.values.location.pathname) {
                // don't clear the parameters if we're already on the right page
                // otherwise we can't use a url with parameters as a landing page
                return
            }
            return [tabUrl, router.values.searchParams, router.values.hashParams]
        },
    })),
    urlToAction(({ actions, values }) => {
        const mappings: Record<string, () => void> = {}

        Object.entries(tabs).forEach(([tabKey, tabConfig]) => {
            const tabEnum = tabKey as DataManagementTab

            // First main tab URLs
            mappings[tabConfig.url] = () => {
                if (values.tab !== tabEnum) {
                    actions.setTab(tabEnum)
                }
            }

            // Then child URLs
            if (tabConfig.children) {
                Object.keys(tabConfig.children).forEach((childUrl) => {
                    mappings[childUrl] = () => {
                        if (values.tab !== tabEnum) {
                            actions.setTab(tabEnum)
                        }
                    }
                })
            }
        })

        return mappings
    }),
])

export function DataManagementScene(): JSX.Element | null {
    const { enabledTabs, tab } = useValues(dataManagementSceneLogic)

    if (enabledTabs.includes(tab)) {
        return <>{tabs[tab].content}</>
    }
    return null
}

export const scene: SceneExport = {
    component: DataManagementScene,
    logic: dataManagementSceneLogic,
}
