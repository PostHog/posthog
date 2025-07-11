import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SidePanelTab } from '~/types'
import { sidePanelStateLogic } from '../../sidePanelStateLogic'
import type { sidePanelInfoLogicType } from './sidePanelInfoLogicType'
import { FEATURE_FLAGS } from 'lib/constants'
import { sidePanelContextLogic } from '../sidePanelContextLogic'

export enum SidePanelInfoTab {
    Info = 'info',
    AccessControl = 'access-control',
    Discussion = 'discussion',
}

export const sidePanelInfoLogic = kea<sidePanelInfoLogicType>([
    path(['layout', 'side-panel', 'info-panel', 'sidePanelInfoLogic']),

    connect(() => ({
        values: [
            featureFlagLogic,
            ['featureFlags'],
            sidePanelContextLogic,
            ['sceneSidePanelContext'],
            sidePanelStateLogic,
            ['selectedTab', 'sidePanelOpen'],
        ],
        actions: [sidePanelStateLogic, ['openSidePanel', 'closeSidePanel']],
    })),

    actions({
        // Register elemnent for portal
        registerSidePanelInfoContentElement: (element: HTMLElement | null) => ({ element }),
        // Set if the scene has a side panel, false by default, true if scene has the element `SidePanelInfoContent`
        setSceneHasSidePanel: (hasSidePanel: boolean) => ({ hasSidePanel }),
        openInfoPanel: true,
        closeInfoPanel: true,
        openAcessControlTab: true,
        closeAcessControlTab: true,
        openDiscussionTab: true,
        closeDiscussionTab: true,
        setActiveTab: (tab: SidePanelInfoTab) => ({ tab }),
    }),

    reducers({
        sceneHasSidePanel: [
            false,
            {
                setSceneHasSidePanel: (_, { hasSidePanel }) => hasSidePanel,
            },
        ],
        isInfoPanelOpen: [
            false,
            {
                openInfoPanel: () => true,
                closeInfoPanel: () => false,
                openAcessControlTab: () => false,
                openDiscussionTab: () => false,
                closeAcessControlTab: () => false,
                closeDiscussionTab: () => false,
            },
        ],
        isAcessControlPanelOpen: [
            false,
            {
                openAcessControlTab: () => true,
                closeAcessControlTab: () => false,
                openDiscussionTab: () => false,
                closeDiscussionTab: () => false,
                openInfoPanel: () => false,
                closeInfoPanel: () => false,
            },
        ],
        isDiscussionPanelOpen: [
            false,
            {
                openDiscussionTab: () => true,
                closeDiscussionTab: () => false,
                openInfoPanel: () => false,
                closeInfoPanel: () => false,
                openAcessControlTab: () => false,
                closeAcessControlTab: () => false,
            },
        ],
        sidePanelInfoContentElement: [
            null as HTMLElement | null,
            {
                registerSidePanelInfoContentElement: (_, { element }) => element,
            },
        ],
        activeTab: [
            SidePanelInfoTab.Info as SidePanelInfoTab,
            { persist: true },
            {
                setActiveTab: (_, { tab }) => tab,
                openInfoPanel: () => SidePanelInfoTab.Info,
                openAcessControlTab: () => SidePanelInfoTab.AccessControl,
                openDiscussionTab: () => SidePanelInfoTab.Discussion,
                closeInfoPanel: () => SidePanelInfoTab.Info,
                closeAcessControlTab: () => SidePanelInfoTab.AccessControl,
                closeDiscussionTab: () => SidePanelInfoTab.Discussion,
            },
        ],
    }),

    selectors({
        isInfoPanelActuallyOpen: [
            (s) => [s.sidePanelOpen, s.selectedTab, s.activeTab],
            (sidePanelOpen: boolean, selectedTab: SidePanelTab, activeTab: SidePanelInfoTab) =>
                sidePanelOpen && selectedTab === SidePanelTab.SceneInfo && activeTab === SidePanelInfoTab.Info,
        ],
        isAcessControlPanelActuallyOpen: [
            (s) => [s.sidePanelOpen, s.selectedTab, s.activeTab],
            (sidePanelOpen: boolean, selectedTab: SidePanelTab, activeTab: SidePanelInfoTab) =>
                sidePanelOpen && selectedTab === SidePanelTab.SceneInfo && activeTab === SidePanelInfoTab.AccessControl,
        ],
        isDiscussionPanelActuallyOpen: [
            (s) => [s.sidePanelOpen, s.selectedTab, s.activeTab],
            (sidePanelOpen: boolean, selectedTab: SidePanelTab, activeTab: SidePanelInfoTab) =>
                sidePanelOpen && selectedTab === SidePanelTab.SceneInfo && activeTab === SidePanelInfoTab.Discussion,
        ],
        sidePanelInfoEnabledTabs: [
            (s) => [s.featureFlags, s.sceneHasSidePanel, s.sceneSidePanelContext],
            (featureFlags, sceneHasSidePanel, sceneSidePanelContext) => {
                const tabs: SidePanelInfoTab[] = []

                if (sceneHasSidePanel) {
                    tabs.push(SidePanelInfoTab.Info)
                }

                if (featureFlags[FEATURE_FLAGS.DISCUSSIONS]) {
                    tabs.push(SidePanelInfoTab.Discussion)
                }

                if (sceneSidePanelContext.access_control_resource && sceneSidePanelContext.access_control_resource_id) {
                    tabs.push(SidePanelInfoTab.AccessControl)
                }

                return tabs
            },
        ],
    }),

    listeners(({ actions }) => ({
        openInfoPanel: () => {
            actions.openSidePanel(SidePanelTab.SceneInfo)
        },
        closeInfoPanel: () => {
            actions.closeSidePanel(SidePanelTab.SceneInfo)
        },
        openAcessControlTab: () => {
            actions.openSidePanel(SidePanelTab.SceneInfo)
        },
        closeAcessControlTab: () => {
            actions.closeSidePanel(SidePanelTab.SceneInfo)
        },
        openDiscussionTab: () => {
            actions.openSidePanel(SidePanelTab.SceneInfo)
        },
        closeDiscussionTab: () => {
            actions.closeSidePanel(SidePanelTab.SceneInfo)
        },
    })),
])
