import { kea, useActions } from 'kea'
import { urls } from 'scenes/urls'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'

import type { dataWarehouseTabsLogicType } from './DataWarehousePageTabsType'

export enum DataWarehouseTab {
    Posthog = 'posthog',
    External = 'external',
    Views = 'views',
}

const tabUrls = {
    [DataWarehouseTab.Posthog]: urls.dataWarehousePosthog(),
    [DataWarehouseTab.External]: urls.dataWarehouseExternal(),
    [DataWarehouseTab.Views]: urls.dataWarehouseSavedQueries(),
}

const dataWarehouseTabsLogic = kea<dataWarehouseTabsLogicType>({
    path: ['scenes', 'warehouse', 'dataWarehouseTabsLogic'],
    actions: {
        setTab: (tab: DataWarehouseTab) => ({ tab }),
    },
    reducers: {
        tab: [
            DataWarehouseTab.Posthog as DataWarehouseTab,
            {
                setTab: (_, { tab }) => tab,
            },
        ],
    },
    actionToUrl: () => ({
        setTab: ({ tab }) => tabUrls[tab as DataWarehouseTab] || urls.dataWarehousePosthog(),
    }),
    urlToAction: ({ actions, values }) => {
        return Object.fromEntries(
            Object.entries(tabUrls).map(([key, url]) => [
                url,
                () => {
                    if (values.tab !== key) {
                        actions.setTab(key as DataWarehouseTab)
                    }
                },
            ])
        )
    },
})

export function DataWarehousePageTabs({ tab }: { tab: DataWarehouseTab }): JSX.Element {
    const { setTab } = useActions(dataWarehouseTabsLogic)

    return (
        <>
            <LemonTabs
                activeKey={tab}
                onChange={(t) => setTab(t)}
                tabs={[
                    {
                        key: DataWarehouseTab.Posthog,
                        label: <span data-attr="data-warehouse-Posthog-tab">Posthog</span>,
                    },
                    {
                        key: DataWarehouseTab.External,
                        label: <span data-attr="data-warehouse-external-tab">External</span>,
                    },
                    {
                        key: DataWarehouseTab.Views,
                        label: <span data-attr="data-warehouse-views-tab">Views</span>,
                    },
                ]}
            />
        </>
    )
}
