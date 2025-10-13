import { actions, afterMount, connect, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { sidePanelStateLogic } from '../sidePanelStateLogic'
import type { sidePanelStatusLogicType } from './sidePanelStatusLogicType'

export type SPIndicator = 'none' | 'minor' | 'major'

export type SPComponentStatus = 'operational' | 'degraded_performance' | 'partial_outage' | 'major_outage'

export interface SPSummary {
    // page: SPPage
    components: SPComponent[]
    incidents: SPIncident[]
    scheduled_maintenances: any[]
    status: SPStatus
}

export interface SPComponent {
    id: string
    name: string
    status: SPComponentStatus
    created_at: Date
    updated_at: Date
    position: number
    description: null | string
    showcase: boolean
    start_date: Date | null
    group_id: null | string
    page_id: string
    group: boolean
    only_show_if_degraded: boolean
    components?: string[]
}

export interface SPIncident {
    id: string
    name: string
    status: string
    created_at: Date
    updated_at: Date
    monitoring_at: null
    resolved_at: null
    impact: string
    shortlink: string
    started_at: Date
    page_id: string
    incident_updates: SPIncidentUpdate[]
    components: SPComponent[]
    reminder_intervals: string
}

export interface SPIncidentUpdate {
    id: string
    status: string
    body: string
    incident_id: string
    created_at: Date
    updated_at: Date
    display_at: Date
    affected_components: SPAffectedComponent[]
    deliver_notifications: boolean
    custom_tweet: null
    tweet_id: null
}

export interface SPAffectedComponent {
    code: string
    name: string
    old_status: string
    new_status: string
}

export interface SPStatus {
    indicator: SPIndicator
    description: string
}

export const STATUS_PAGE_BASE = 'https://status.posthog.com'

// NOTE: Test account with some incidents - ask @benjackwhite for access
// export const STATUS_PAGE_BASE = 'https://posthogtesting.statuspage.io'

// Map the hostname to relevant groups (found via the summary.json endpoint)
const RELEVANT_GROUPS_MAP = {
    'us.posthog.com': ['41df083ftqt6', 'z0y6m9kyvy3j'],
    'eu.posthog.com': ['c4d9jd1jcx3f', 'nfknrn2bf3yz'],
    localhost: ['f58xx1143yvt', 't3rdjq2z0x7p'], // localhost has IDs for the test status page - that way we really only show it if local dev and overridden to use the other status page
}

export const REFRESH_INTERVAL = 60 * 1000 * 5 // 5 minutes

export const sidePanelStatusLogic = kea<sidePanelStatusLogicType>([
    path(['scenes', 'navigation', 'sidepanel', 'sidePanelStatusLogic']),
    connect(() => ({
        actions: [sidePanelStateLogic, ['openSidePanel', 'closeSidePanel']],
    })),

    actions({
        loadStatusPage: true,
        setPageVisibility: (visible: boolean) => ({ visible }),
    }),

    reducers(() => ({
        // Persisted copy to avoid flash effect on page load
        status: [
            'operational' as SPComponentStatus,
            { persist: true },
            {
                loadStatusPageSuccess: (_, { statusPage }) => {
                    const relevantGroups = RELEVANT_GROUPS_MAP[window.location.hostname]
                    if (!relevantGroups) {
                        return 'operational'
                    }

                    const componentStatus = statusPage.components.find(
                        ({ group_id, status }) =>
                            group_id && relevantGroups.includes(group_id) && status !== 'operational'
                    )?.status

                    return componentStatus || 'operational'
                },
                loadStatusPageFailure: () => 'operational',
            },
        ],
    })),

    loaders(() => ({
        statusPage: [
            null as SPSummary | null,
            {
                loadStatusPage: async () => {
                    const response = await fetch(`${STATUS_PAGE_BASE}/api/v2/summary.json`)
                    const data: SPSummary = await response.json()

                    return data
                },
            },
        ],
    })),

    listeners(({ actions, cache }) => ({
        loadStatusPageSuccess: () => {
            cache.disposables.add(() => {
                const timerId = setTimeout(() => actions.loadStatusPage(), REFRESH_INTERVAL)
                return () => clearTimeout(timerId)
            }, 'refreshTimeout')
        },
        setPageVisibility: ({ visible }) => {
            if (visible) {
                actions.loadStatusPage()
            } else {
                cache.disposables.dispose('refreshTimeout')
            }
        },
    })),

    afterMount(({ actions, cache }) => {
        actions.loadStatusPage()
        cache.disposables.add(() => {
            const onVisibilityChange = (): void => {
                actions.setPageVisibility(document.visibilityState === 'visible')
            }
            document.addEventListener('visibilitychange', onVisibilityChange)
            return () => document.removeEventListener('visibilitychange', onVisibilityChange)
        }, 'visibilityListener')
    }),
])
