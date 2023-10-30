import { actionToUrl, urlToAction } from 'kea-router'
import { kea, useActions, useValues, path, actions, reducers } from 'kea'
import { urls } from 'scenes/urls'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'

import type { dataWarehouseTabsLogicType } from './DataWarehousePageTabsType'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

export enum DataWarehouseTab {
    Posthog = 'posthog',
    External = 'external',
    Views = 'views',
}

const tabUrls = {
    [DataWarehouseTab.External]: urls.dataWarehouseExternal(),
    [DataWarehouseTab.Posthog]: urls.dataWarehousePosthog(),
    [DataWarehouseTab.Views]: urls.dataWarehouseSavedQueries(),
}

const dataWarehouseTabsLogic = kea<dataWarehouseTabsLogicType>([
    path(['scenes', 'warehouse', 'dataWarehouseTabsLogic']),
    actions({
        setTab: (tab: DataWarehouseTab) => ({ tab }),
    }),
    reducers({
        tab: [
            DataWarehouseTab.External as DataWarehouseTab,
            {
                setTab: (_, { tab }) => tab,
            },
        ],
    }),
    actionToUrl(() => ({
        setTab: ({ tab }) => tabUrls[tab as DataWarehouseTab] || urls.dataWarehousePosthog(),
    })),
    urlToAction(({ actions, values }) => {
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
    }),
])

export function DataWarehousePageTabs({ tab }: { tab: DataWarehouseTab }): JSX.Element {
    const { setTab } = useActions(dataWarehouseTabsLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    return (
        <>
            <LemonTabs
                activeKey={tab}
                onChange={(t) => setTab(t)}
                tabs={[
                    {
                        key: DataWarehouseTab.External,
                        label: <span data-attr="data-warehouse-external-tab">External</span>,
                    },
                    {
                        key: DataWarehouseTab.Posthog,
                        label: <span data-attr="data-warehouse-Posthog-tab">Posthog</span>,
                    },
                    ...(featureFlags[FEATURE_FLAGS.DATA_WAREHOUSE_VIEWS]
                        ? [
                              {
                                  key: DataWarehouseTab.Views,
                                  label: <span data-attr="data-warehouse-views-tab">Views</span>,
                              },
                          ]
                        : []),
                ]}
            />
        </>
    )
}
