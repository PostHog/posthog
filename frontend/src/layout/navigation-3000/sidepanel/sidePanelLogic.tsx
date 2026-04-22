import { connect, kea, path, selectors } from 'kea'
import { combineUrl, router, urlToAction } from 'kea-router'

import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { sceneLayoutLogic } from '~/layout/scenes/sceneLayoutLogic'
import { SidePanelTab } from '~/types'

import { sidePanelContextLogic } from './sidePanelContextLogic'
import type { sidePanelLogicType } from './sidePanelLogicType'
import { sidePanelStateLogic } from './sidePanelStateLogic'

const TABS_REQUIRING_A_TEAM = [
    SidePanelTab.Max,
    SidePanelTab.Notebooks,
    SidePanelTab.Activity,
    SidePanelTab.Discussion,
    SidePanelTab.AccessControl,
    SidePanelTab.Exports,
]

export const sidePanelLogic = kea<sidePanelLogicType>([
    path(['scenes', 'navigation', 'sidepanel', 'sidePanelLogic']),
    connect(() => ({
        values: [
            sidePanelStateLogic,
            ['selectedTab', 'sidePanelOpen'],
            sidePanelContextLogic,
            ['sceneSidePanelContext'],
            teamLogic,
            ['currentTeam'],
            sceneLayoutLogic,
            ['scenePanelIsPresent'],
            preflightLogic,
            ['isCloudOrDev'],
        ],
        actions: [sidePanelStateLogic, ['closeSidePanel', 'openSidePanel']],
    })),

    selectors({
        enabledTabs: [
            (s) => [s.sceneSidePanelContext, s.currentTeam, s.scenePanelIsPresent, s.isCloudOrDev],
            (sceneSidePanelContext, currentTeam, scenePanelIsPresent, isCloudOrDev) => {
                const tabs: SidePanelTab[] = []

                if (scenePanelIsPresent) {
                    tabs.push(SidePanelTab.Info)
                }

                tabs.push(SidePanelTab.Max)
                tabs.push(SidePanelTab.Notebooks)

                if (sceneSidePanelContext?.activity_scope) {
                    tabs.push(SidePanelTab.Activity)
                }
                tabs.push(SidePanelTab.Discussion)

                if (sceneSidePanelContext.access_control_resource && sceneSidePanelContext.access_control_resource_id) {
                    tabs.push(SidePanelTab.AccessControl)
                }

                if (sceneSidePanelContext.settings_section) {
                    tabs.push(SidePanelTab.Settings)
                }

                // Exports and Support are openable programmatically but not shown in the nav bar
                tabs.push(SidePanelTab.Exports)

                if (isCloudOrDev) {
                    tabs.push(SidePanelTab.Support)
                }

                if (!currentTeam) {
                    return tabs.filter((tab) => !TABS_REQUIRING_A_TEAM.includes(tab))
                }

                return tabs
            },
        ],

        /** Tabs shown in the navigation bar */
        visibleTabs: [
            (s) => [s.enabledTabs],
            (enabledTabs): SidePanelTab[] => {
                // Some tabs are openable programmatically but not shown in the nav bar
                const hiddenTabs = [SidePanelTab.Exports]
                return enabledTabs.filter((tab) => !hiddenTabs.includes(tab))
            },
        ],
    }),
    urlToAction(() => {
        return {
            '/': (_, _searchParams, hashParams): void => {
                // Redirect old feature preview side panel links to new settings page
                if (hashParams.panel?.startsWith('feature-previews')) {
                    // it will be encoded as %3A, so we need to split on :
                    const parts = hashParams.panel.split(':')
                    // from: ${url}/#panel=feature-previews
                    // to:   ${url}/settings/user-feature-previews
                    if (parts.length > 1) {
                        // from: ${url}/#panel=feature-previews%3A${flagKey} or ${url}/#panel=feature-previews:${flagKey}
                        // to:   ${url}/settings/user-feature-previews#${flagKey}
                        router.actions.replace(combineUrl(urls.settings('user-feature-previews'), {}, parts[1]).url)
                    } else {
                        router.actions.replace(urls.settings('user-feature-previews'))
                    }
                }
            },
        }
    }),
])
