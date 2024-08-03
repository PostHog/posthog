import { IconInfo } from '@posthog/icons'
import { actions, connect, kea, path, reducers, selectors, useActions, useValues } from 'kea'
import { actionToUrl, combineUrl, router, urlToAction } from 'kea-router'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { PageHeader } from 'lib/components/PageHeader'
import { TitleWithIcon } from 'lib/components/TitleWithIcon'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { capitalizeFirstLetter } from 'lib/utils'
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
}

const tabs: Record<
    DataManagementTab,
    { url: string; label: LemonTab<any>['label']; content: JSX.Element; buttons?: React.ReactNode }
> = {
    [DataManagementTab.EventDefinitions]: {
        url: urls.eventDefinitions(),
        label: 'Events',
        content: <EventDefinitionsTable />,
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
    },
    [DataManagementTab.Annotations]: {
        url: urls.annotations(),
        content: <Annotations />,
        label: 'Annotations',
        buttons: <NewAnnotationButton />,
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
    },
    [DataManagementTab.IngestionWarnings]: {
        url: urls.ingestionWarnings(),
        label: 'Ingestion warnings',
        content: <IngestionWarningsView />,
    },
}

const dataManagementSceneLogic = kea<dataManagementSceneLogicType>([
    path(['scenes', 'events', 'dataManagementSceneLogic']),
    connect({
        values: [featureFlagLogic, ['featureFlags']],
    }),
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
                        name: `Data Management`,
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
        showWarningsTab: [
            (s) => [s.featureFlags],
            (featureFlags): boolean => !!featureFlags[FEATURE_FLAGS.INGESTION_WARNINGS_ENABLED],
        ],
        enabledTabs: [
            (s) => [s.showWarningsTab],
            (showWarningsTab): DataManagementTab[] => {
                const allTabs = Object.keys(tabs)

                return allTabs.filter((x) => {
                    return x === DataManagementTab.IngestionWarnings ? showWarningsTab : true
                }) as DataManagementTab[]
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
            return tabUrl
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
