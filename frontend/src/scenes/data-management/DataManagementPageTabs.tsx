import { actionToUrl, urlToAction } from 'kea-router'
import { kea, useActions, useValues, path, connect, actions, reducers, selectors } from 'kea'
import { urls } from 'scenes/urls'
import type { eventsTabsLogicType } from './DataManagementPageTabsType'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { IconInfo } from 'lib/lemon-ui/icons'
import { TitleWithIcon } from 'lib/components/TitleWithIcon'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'

export enum DataManagementTab {
    Actions = 'actions',
    EventDefinitions = 'events',
    PropertyDefinitions = 'properties',
    History = 'history',
    IngestionWarnings = 'warnings',
    Database = 'database',
}

const tabUrls = {
    [DataManagementTab.PropertyDefinitions]: urls.propertyDefinitions(),
    [DataManagementTab.EventDefinitions]: urls.eventDefinitions(),
    [DataManagementTab.Actions]: urls.actions(),
    [DataManagementTab.History]: urls.dataManagementHistory(),
    [DataManagementTab.IngestionWarnings]: urls.ingestionWarnings(),
    [DataManagementTab.Database]: urls.database(),
}

const eventsTabsLogic = kea<eventsTabsLogicType>([
    path(['scenes', 'events', 'eventsTabsLogic']),
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
        showWarningsTab: [
            (s) => [s.featureFlags],
            (featureFlags): boolean => !!featureFlags[FEATURE_FLAGS.INGESTION_WARNINGS_ENABLED],
        ],
    }),
    actionToUrl(() => ({
        setTab: ({ tab }) => tabUrls[tab as DataManagementTab] || urls.events(),
    })),
    urlToAction(({ actions, values }) => {
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
    }),
])

export function DataManagementPageTabs({ tab }: { tab: DataManagementTab }): JSX.Element {
    const { showWarningsTab } = useValues(eventsTabsLogic)
    const { setTab } = useActions(eventsTabsLogic)

    return (
        <>
            <LemonTabs
                activeKey={tab}
                onChange={(t) => setTab(t)}
                tabs={[
                    {
                        key: DataManagementTab.EventDefinitions,
                        label: <span data-attr="data-management-events-tab">Events</span>,
                    },
                    {
                        key: DataManagementTab.Actions,
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
                    },
                    {
                        key: DataManagementTab.PropertyDefinitions,
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
                    },
                    {
                        key: DataManagementTab.History,
                        label: <span data-attr="data-management-history-tab">History</span>,
                    },

                    showWarningsTab && {
                        key: DataManagementTab.IngestionWarnings,
                        label: <span data-attr="data-management-warnings-tab">Ingestion Warnings</span>,
                    },

                    {
                        key: DataManagementTab.Database,
                        label: (
                            <span data-attr="data-management-database-tab">
                                Database
                                <LemonTag type="warning" className="uppercase ml-2">
                                    Beta
                                </LemonTag>
                            </span>
                        ),
                    },
                ]}
            />
        </>
    )
}
