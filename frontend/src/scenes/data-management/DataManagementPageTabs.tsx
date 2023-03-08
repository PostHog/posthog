import { kea, useActions, useValues } from 'kea'
import { Tabs } from 'antd'
import { urls } from 'scenes/urls'
import type { eventsTabsLogicType } from './DataManagementPageTabsType'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { IconInfo } from 'lib/lemon-ui/icons'
import { TitleWithIcon } from 'lib/components/TitleWithIcon'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

export enum DataManagementTab {
    Actions = 'actions',
    EventDefinitions = 'events',
    PropertyDefinitions = 'properties',
    IngestionWarnings = 'warnings',
}

const tabUrls = {
    [DataManagementTab.PropertyDefinitions]: urls.propertyDefinitions(),
    [DataManagementTab.EventDefinitions]: urls.eventDefinitions(),
    [DataManagementTab.Actions]: urls.actions(),
    [DataManagementTab.IngestionWarnings]: urls.ingestionWarnings(),
}

const eventsTabsLogic = kea<eventsTabsLogicType>({
    path: ['scenes', 'events', 'eventsTabsLogic'],
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
    },
    actionToUrl: () => ({
        setTab: ({ tab }) => tabUrls[tab as DataManagementTab] || urls.events(),
    }),
    urlToAction: ({ actions, values }) => {
        return Object.fromEntries(
            Object.entries(tabUrls).map(([key, url]) => [
                url,
                () => {
                    if (values.tab !== key) {
                        actions.setTab(key as DataManagementTab)
                    }
                },
            ])
        )
    },
})

export function DataManagementPageTabs({ tab }: { tab: DataManagementTab }): JSX.Element {
    const { showWarningsTab } = useValues(eventsTabsLogic)
    const { setTab } = useActions(eventsTabsLogic)
    return (
        <Tabs tabPosition="top" animated={false} activeKey={tab} onTabClick={(t) => setTab(t as DataManagementTab)}>
            <Tabs.TabPane
                tab={<span data-attr="data-management-events-tab">Events</span>}
                key={DataManagementTab.EventDefinitions}
            />
            <Tabs.TabPane
                tab={
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
                }
                key={DataManagementTab.Actions}
            />
            <Tabs.TabPane
                tab={
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
                }
                key={DataManagementTab.PropertyDefinitions}
            />
            {showWarningsTab && (
                <Tabs.TabPane
                    tab={<span data-attr="data-management-warnings-tab">Ingestion Warnings</span>}
                    key={DataManagementTab.IngestionWarnings}
                />
            )}
        </Tabs>
    )
}
