import { actions, kea, path, reducers, selectors } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { urls } from 'scenes/urls'

import { SIDE_PANEL_CONTEXT_KEY, SidePanelSceneContext } from '~/layout/navigation-3000/sidepanel/types'

import type { dataWarehouseSceneLogicType } from './dataWarehouseSceneLogicType'

// The Data ops scene renders the managed-warehouse settings by default. When the
// data-modeling-tab flag is on, the scene becomes tabbed (Settings + Modeling); this
// logic owns the active-tab state and its URL sync, plus the scene's side-panel
// access-control context.
export enum DataWarehouseTab {
    SETTINGS = 'settings',
    MODELING = 'modeling',
}

export const dataWarehouseSceneLogic = kea<dataWarehouseSceneLogicType>([
    path(['scenes', 'data-warehouse', 'dataWarehouseSceneLogic']),
    actions({
        setActiveTab: (tab: DataWarehouseTab) => ({ tab }),
    }),
    reducers({
        activeTab: [
            DataWarehouseTab.SETTINGS as DataWarehouseTab,
            {
                setActiveTab: (_, { tab }) => tab,
            },
        ],
    }),
    selectors({
        [SIDE_PANEL_CONTEXT_KEY]: [
            () => [],
            (): SidePanelSceneContext => ({
                access_control_resource: 'warehouse_objects',
            }),
        ],
    }),
    urlToAction(({ actions, values }) => ({
        [urls.dataOps()]: (_, searchParams) => {
            const tab = searchParams.tab as DataWarehouseTab | undefined
            if (tab && Object.values(DataWarehouseTab).includes(tab) && tab !== values.activeTab) {
                actions.setActiveTab(tab)
            } else if (!tab && values.activeTab !== DataWarehouseTab.SETTINGS) {
                actions.setActiveTab(DataWarehouseTab.SETTINGS)
            }
        },
    })),
    actionToUrl(({ values }) => ({
        setActiveTab: () => {
            const searchParams = { ...router.values.searchParams }
            if (values.activeTab === DataWarehouseTab.SETTINGS) {
                delete searchParams.tab
            } else {
                searchParams.tab = values.activeTab
            }
            return [urls.dataOps(), searchParams]
        },
    })),
])
