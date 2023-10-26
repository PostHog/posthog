import { kea, useActions, useValues } from 'kea'
import { urls } from 'scenes/urls'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { IconInfo } from 'lib/lemon-ui/icons'
import { TitleWithIcon } from 'lib/components/TitleWithIcon'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import React from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import { PageHeader } from 'lib/components/PageHeader'
import { NewActionButton } from 'scenes/actions/NewActionButton'
import { Annotations } from 'scenes/annotations'

import type { dataManagementSceneLogicType } from './DataManagementSceneType'
import { NewAnnotationButton } from 'scenes/annotations/AnnotationModal'
import { EventDefinitionsTable } from './events/EventDefinitionsTable'
import { ActionsTable } from './actions/ActionsTable'
import { PropertyDefinitionsTable } from './properties/PropertyDefinitionsTable'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { ActivityScope } from 'lib/components/ActivityLog/humanizeActivity'
import { IngestionWarningsView } from './ingestion-warnings/IngestionWarningsView'
import { DatabaseTableList } from './database/DatabaseTableList'

export const scene: SceneExport = {
    component: DataManagementScene,
}

export enum DataManagementTab {
    Actions = 'actions',
    EventDefinitions = 'events',
    PropertyDefinitions = 'properties',
    Annotations = 'annotations',
    History = 'history',
    IngestionWarnings = 'warnings',
    Database = 'database',
}

const tabs: Record<
    DataManagementTab,
    { url: string; label: LemonTab<any>['label']; children: React.ReactNode; buttons?: React.ReactNode }
> = {
    [DataManagementTab.EventDefinitions]: {
        url: urls.eventDefinitions(),
        label: 'Events',
        buttons: <NewActionButton />,
        children: <EventDefinitionsTable />,
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
                data-attr="data-management-actions-tab"
            >
                Actions
            </TitleWithIcon>
        ),
        children: <ActionsTable />,
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
                data-attr="data-management-event-properties-tab"
            >
                Properties
            </TitleWithIcon>
        ),
        children: <PropertyDefinitionsTable />,
    },
    [DataManagementTab.Annotations]: {
        url: urls.annotations(),
        children: <Annotations />,
        label: 'Annotations',
        buttons: <NewAnnotationButton />,
    },
    [DataManagementTab.History]: {
        url: urls.dataManagementHistory(),
        label: 'History',
        children: (
            <ActivityLog
                scope={ActivityScope.DATA_MANAGEMENT}
                caption={
                    'Only actions taken in the UI are captured in History. Automatic creation of definitions by ingestion is not shown here.'
                }
            />
        ),
    },
    // TODO: Only show this if it should be shown
    [DataManagementTab.IngestionWarnings]: {
        url: urls.ingestionWarnings(),
        label: 'Ingestion Warnings',
        children: <IngestionWarningsView />,
    },
    [DataManagementTab.Database]: {
        url: urls.database(),
        label: (
            <>
                Database
                <LemonTag type="warning" className="uppercase ml-2">
                    Beta
                </LemonTag>
            </>
        ),
        children: <DatabaseTableList />,
    },
}

const dataManagementSceneLogic = kea<dataManagementSceneLogicType>({
    path: ['scenes', 'events', 'dataManagementSceneLogic'],
    connect: {
        values: [featureFlagLogic, ['featureFlags']],
    },
    actions: {
        setTab: (tab: DataManagementTab) => ({ tab }),
    },
    reducers: {
        tab: [
            DataManagementTab.EventDefinitions as DataManagementTab,
            {
                setTab: (_, { tab }) => tab,
            },
        ],
    },
    selectors: {
        showWarningsTab: [
            (s) => [s.featureFlags],
            (featureFlags): boolean => !!featureFlags[FEATURE_FLAGS.INGESTION_WARNINGS_ENABLED],
        ],
        enabledTabs: [
            (s) => [s.showWarningsTab],
            (showWarningsTab): DataManagementTab[] => {
                const allTabs = Object.keys(tabs)

                return allTabs.filter((x) => {
                    if (x === DataManagementTab.IngestionWarnings) {
                        return showWarningsTab
                    }
                    return true
                }) as DataManagementTab[]
            },
        ],
    },
    actionToUrl: () => ({
        setTab: ({ tab }) => tabs[tab as DataManagementTab]?.url || urls.events(),
    }),
    urlToAction: ({ actions, values }) => {
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
    },
})

export function DataManagementScene(): JSX.Element {
    const { enabledTabs, tab } = useValues(dataManagementSceneLogic)
    const { setTab } = useActions(dataManagementSceneLogic)

    const lemonTabs: LemonTab<DataManagementTab>[] = enabledTabs.map((key) => ({
        key: key as DataManagementTab,
        label: <span data-attr={`data-management-${key}-tab`}>{tabs[key].label}</span>,
    }))

    return (
        <>
            <PageHeader
                title="Data Management"
                caption="Use data management to organize events that come into PostHog. Reduce noise, clarify usage, and help collaborators get the most value from your data."
                tabbedPage
                buttons={<>{tabs[tab].buttons}</>}
            />

            <LemonTabs activeKey={tab} onChange={(t) => setTab(t)} tabs={lemonTabs} />

            {tabs[tab].children}
        </>
    )
}
