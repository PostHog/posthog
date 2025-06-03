import { IconInfo } from '@posthog/icons'
import { actions, connect, kea, path, reducers, selectors, useActions, useValues } from 'kea'
import { actionToUrl, combineUrl, router, urlToAction } from 'kea-router'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { PageHeader } from 'lib/components/PageHeader'
import { TitleWithIcon } from 'lib/components/TitleWithIcon'
import { FEATURE_FLAGS, FeatureFlagKey } from 'lib/constants'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { capitalizeFirstLetter } from 'lib/utils'
import { RevenueAnalyticsSettings } from 'products/revenue_analytics/frontend/settings/RevenueAnalyticsSettings'
import React from 'react'
import { NewActionButton } from 'scenes/actions/NewActionButton'
import { Annotations } from 'scenes/annotations'
import { NewAnnotationButton } from 'scenes/annotations/AnnotationModal'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { ActivityScope, Breadcrumb } from '~/types'

import { ActionsTable } from './actions/ActionsTable'
import type { dataManagementSceneLogicType } from './DataManagementSceneType'
import { EventDefinitionsTable } from './events/EventDefinitionsTable'
import { IngestionWarningsView } from './ingestion-warnings/IngestionWarningsView'
import { PropertyDefinitionsTable } from './properties/PropertyDefinitionsTable'

export enum DataManagementTab {
    Actions = 'actions',
    EventDefinitions = 'events',
    PropertyDefinitions = 'properties',
    Annotations = 'annotations',
    History = 'history',
    IngestionWarnings = 'warnings',
    Revenue = 'revenue',
}
const tabs: Record<
    DataManagementTab,
    {
        url: string
        label: LemonTab<any>['label']
        content: JSX.Element
        buttons?: React.ReactNode
        flag?: FeatureFlagKey
        tooltipDocLink?: string
    }
> = {
    [DataManagementTab.EventDefinitions]: {
        url: urls.eventDefinitions(),
        label: 'Events',
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
    [DataManagementTab.Annotations]: {
        url: urls.annotations(),
        content: <Annotations />,
        label: 'Annotations',
        buttons: <NewAnnotationButton />,
        tooltipDocLink: 'https://posthog.com/docs/data/annotations',
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
                return [
                    {
                        key: Scene.DataManagement,
                        name: `Data management`,
                        path: tabs.events.url,
                    },
                    {
                        key: tab,
                        name: capitalizeFirstLetter(tab),
                        path: tabs[tab].url,
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
        return Object.fromEntries(
            Object.entries(tabs).map(([key, tab]) => [
                tab.url,
                () => {
                    if (values.tab !== key) {
                        actions.setTab(key as DataManagementTab)
                    }
                },
            ])
        )
    }),
])

export function DataManagementScene(): JSX.Element {
    const { enabledTabs, tab } = useValues(dataManagementSceneLogic)
    const { setTab } = useActions(dataManagementSceneLogic)

    const lemonTabs: LemonTab<DataManagementTab>[] = enabledTabs.map((key) => ({
        key: key as DataManagementTab,
        label: <span data-attr={`data-management-${key}-tab`}>{tabs[key].label}</span>,
        content: tabs[key].content,
        tooltipDocLink: tabs[key].tooltipDocLink,
    }))

    return (
        <>
            <PageHeader
                caption="Use data management to organize events that come into PostHog. Reduce noise, clarify usage, and help collaborators get the most value from your data."
                tabbedPage
                buttons={<>{tabs[tab].buttons}</>}
            />

            <LemonTabs activeKey={tab} onChange={(t) => setTab(t)} tabs={lemonTabs} />
        </>
    )
}

export const scene: SceneExport = {
    component: DataManagementScene,
    logic: dataManagementSceneLogic,
}
