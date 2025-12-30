import { connect, kea, path, selectors } from 'kea'
import { combineUrl, router, urlToAction } from 'kea-router'

import { dayjs } from 'lib/dayjs'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { activationLogic } from '~/layout/navigation-3000/sidepanel/panels/activation/activationLogic'
import { sidePanelNotificationsLogic } from '~/layout/navigation-3000/sidepanel/panels/activity/sidePanelNotificationsLogic'
import { AvailableFeature, SidePanelTab } from '~/types'

import { sidePanelContextLogic } from './panels/sidePanelContextLogic'
import { sidePanelHealthLogic } from './panels/sidePanelHealthLogic'
import { sidePanelSdkDoctorLogic } from './panels/sidePanelSdkDoctorLogic'
import { sidePanelStatusIncidentIoLogic } from './panels/sidePanelStatusIncidentIoLogic'
import { sidePanelStatusLogic } from './panels/sidePanelStatusLogic'
import type { sidePanelLogicType } from './sidePanelLogicType'
import { sidePanelStateLogic } from './sidePanelStateLogic'

const ALWAYS_EXTRA_TABS = [
    SidePanelTab.Settings,
    SidePanelTab.Activity,
    SidePanelTab.Status,
    SidePanelTab.Exports,
    SidePanelTab.SdkDoctor,
    SidePanelTab.Health,
    SidePanelTab.Changelog,
]

const TABS_REQUIRING_A_TEAM = [
    SidePanelTab.Max,
    SidePanelTab.Notebooks,
    SidePanelTab.Activity,
    SidePanelTab.Activation,
    SidePanelTab.Discussion,
    SidePanelTab.AccessControl,
    SidePanelTab.Exports,
    SidePanelTab.Health,
]

export const sidePanelLogic = kea<sidePanelLogicType>([
    path(['scenes', 'navigation', 'sidepanel', 'sidePanelLogic']),
    connect(() => ({
        values: [
            preflightLogic,
            ['isCloudOrDev'],
            activationLogic,
            ['shouldShowActivationTab'],
            sidePanelStateLogic,
            ['selectedTab', 'sidePanelOpen'],
            // We need to mount this to ensure that marking as read works when the panel closes
            sidePanelNotificationsLogic,
            ['unreadCount'],
            sidePanelStatusLogic,
            ['status'],
            sidePanelStatusIncidentIoLogic,
            ['status as incidentioStatus'],
            sidePanelSdkDoctorLogic,
            ['needsAttention'],
            sidePanelHealthLogic,
            ['hasIssues'],
            userLogic,
            ['hasAvailableFeature'],
            sidePanelContextLogic,
            ['sceneSidePanelContext'],
            teamLogic,
            ['currentTeam'],
        ],
        actions: [sidePanelStateLogic, ['closeSidePanel', 'openSidePanel']],
    })),

    selectors({
        enabledTabs: [
            (s) => [s.isCloudOrDev, s.sceneSidePanelContext, s.currentTeam],
            (isCloudOrDev, sceneSidePanelContext, currentTeam) => {
                const tabs: SidePanelTab[] = []

                /* Always show PostHog AI at the top of the tabs list
                 * ALL DEVS, add an F for Max if you are here and you see this:
                 *  F
                 */
                tabs.push(SidePanelTab.Max)

                if (isCloudOrDev) {
                    tabs.push(SidePanelTab.Status)
                }

                // Quick start is shown in the sidebar for the first 90 days of a team's existence
                if (currentTeam?.created_at) {
                    const teamCreatedAt = dayjs(currentTeam.created_at)

                    if (dayjs().diff(teamCreatedAt, 'day') < 90) {
                        tabs.push(SidePanelTab.Activation)
                    }
                }

                tabs.push(SidePanelTab.Notebooks)
                tabs.push(SidePanelTab.Docs)
                if (isCloudOrDev) {
                    tabs.push(SidePanelTab.Support)
                }

                tabs.push(SidePanelTab.Activity)
                tabs.push(SidePanelTab.Discussion)

                if (sceneSidePanelContext.access_control_resource && sceneSidePanelContext.access_control_resource_id) {
                    tabs.push(SidePanelTab.AccessControl)
                }

                tabs.push(SidePanelTab.Exports)
                tabs.push(SidePanelTab.Settings)
                tabs.push(SidePanelTab.SdkDoctor)
                tabs.push(SidePanelTab.Health)
                tabs.push(SidePanelTab.Changelog)

                if (!currentTeam) {
                    return tabs.filter((tab) => !TABS_REQUIRING_A_TEAM.includes(tab))
                }

                return tabs
            },
        ],

        visibleTabs: [
            (s) => [
                s.enabledTabs,
                s.selectedTab,
                s.sidePanelOpen,
                s.unreadCount,
                s.status,
                s.incidentioStatus,
                s.needsAttention,
                s.hasIssues,
                s.hasAvailableFeature,
                s.shouldShowActivationTab,
            ],
            (
                enabledTabs,
                selectedTab,
                sidePanelOpen,
                unreadCount,
                status,
                incidentioStatus,
                needsAttention,
                hasIssues,
                hasAvailableFeature,
                shouldShowActivationTab
            ): SidePanelTab[] => {
                return enabledTabs.filter((tab) => {
                    if (tab === selectedTab && sidePanelOpen) {
                        return true
                    }

                    if (
                        tab === SidePanelTab.Activity &&
                        unreadCount &&
                        hasAvailableFeature(AvailableFeature.AUDIT_LOGS)
                    ) {
                        return true
                    }

                    if (
                        tab === SidePanelTab.Status &&
                        (status !== 'operational' || incidentioStatus !== 'operational')
                    ) {
                        return true
                    }

                    if (tab === SidePanelTab.SdkDoctor && needsAttention) {
                        return true
                    }

                    if (tab === SidePanelTab.Health && hasIssues) {
                        return true
                    }

                    if (tab === SidePanelTab.Activation && !shouldShowActivationTab) {
                        return false
                    }

                    // Hide certain tabs unless they are selected
                    if (ALWAYS_EXTRA_TABS.includes(tab)) {
                        return false
                    }

                    return true
                })
            },
        ],

        extraTabs: [
            (s) => [s.enabledTabs, s.visibleTabs],
            (enabledTabs, visibleTabs): SidePanelTab[] => {
                return enabledTabs.filter((tab: any) => !visibleTabs.includes(tab))
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
