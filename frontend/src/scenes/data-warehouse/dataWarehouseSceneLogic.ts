import { actions, connect, kea, path, reducers, selectors } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { SIDE_PANEL_CONTEXT_KEY, SidePanelSceneContext } from '~/layout/navigation-3000/sidepanel/types'

import type { dataWarehouseSceneLogicType } from './dataWarehouseSceneLogicType'

export enum DataWarehouseTab {
    SETTINGS = 'settings',
    MODELING = 'modeling',
}

// Single source of truth for which tabs the Data ops scene exposes. Each tab is available
// iff its feature flag is on — crucially Settings (the managed-warehouse UI) is gated by
// the same `provision-managed-warehouse-beta` flag the backend enforces, so the UI never
// shows a Settings tab whose API calls would 403. The scene, the URL state, and the
// default tab all derive from availableTabs / activeTab below.
export const dataWarehouseSceneLogic = kea<dataWarehouseSceneLogicType>([
    path(['scenes', 'data-warehouse', 'dataWarehouseSceneLogic']),
    connect(() => ({
        values: [featureFlagLogic, ['featureFlags']],
    })),
    actions({
        setActiveTab: (tab: DataWarehouseTab) => ({ tab }),
    }),
    reducers({
        selectedTab: [
            DataWarehouseTab.SETTINGS as DataWarehouseTab,
            {
                setActiveTab: (_, { tab }) => tab,
            },
        ],
    }),
    selectors({
        availableTabs: [
            (s) => [s.featureFlags],
            (featureFlags): DataWarehouseTab[] => {
                const tabs: DataWarehouseTab[] = []
                if (featureFlags[FEATURE_FLAGS.PROVISION_MANAGED_WAREHOUSE_BETA]) {
                    tabs.push(DataWarehouseTab.SETTINGS)
                }
                if (featureFlags[FEATURE_FLAGS.DATA_MODELING_TAB]) {
                    tabs.push(DataWarehouseTab.MODELING)
                }
                return tabs
            },
        ],
        // The selected tab clamped to what's actually available (null when nothing is).
        activeTab: [
            (s) => [s.selectedTab, s.availableTabs],
            (selectedTab, availableTabs): DataWarehouseTab | null =>
                availableTabs.includes(selectedTab) ? selectedTab : (availableTabs[0] ?? null),
        ],
        [SIDE_PANEL_CONTEXT_KEY]: [
            () => [],
            (): SidePanelSceneContext => ({
                access_control_resource: 'warehouse_objects',
            }),
        ],
    }),
    urlToAction(({ actions, values }) => ({
        [urls.dataOps()]: (_, searchParams) => {
            const requested = searchParams.tab as DataWarehouseTab | undefined
            const target =
                requested && values.availableTabs.includes(requested)
                    ? requested
                    : (values.availableTabs[0] ?? DataWarehouseTab.SETTINGS)
            if (target !== values.selectedTab) {
                actions.setActiveTab(target)
            }
        },
    })),
    actionToUrl(({ values }) => ({
        setActiveTab: () => {
            const searchParams = { ...router.values.searchParams }
            // The default (first available) tab is canonical at /data-ops with no ?tab.
            if (values.activeTab && values.activeTab !== values.availableTabs[0]) {
                searchParams.tab = values.activeTab
            } else {
                delete searchParams.tab
            }
            return [urls.dataOps(), searchParams]
        },
    })),
])
