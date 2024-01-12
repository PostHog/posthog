import { actions, afterMount, beforeUnmount, connect, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { sidePanelStateLogic } from '../sidePanelStateLogic'
import type { sidePanelStatusLogicType } from './sidePanelStatusLogicType'

export type StatusPageIndicator = 'none' | 'minor' | 'major'

export type StatusPageResponse = {
    status: {
        indicator: StatusPageIndicator
        description: string
    }
}

export const STATUS_PAGE_BASE = 'https://posthogtesting.statuspage.io'
// export const STATUS_PAGE_BASE = 'https://status.posthog.com'

export const REFRESH_INTERVAL = 60000

export const sidePanelStatusLogic = kea<sidePanelStatusLogicType>([
    path(['scenes', 'navigation', 'sidepanel', 'sidePanelStatusLogic']),
    connect({
        values: [featureFlagLogic, ['featureFlags']],
        actions: [sidePanelStateLogic, ['openSidePanel', 'closeSidePanel']],
    }),

    actions({
        loadStatusPage: true,
    }),

    reducers(() => ({
        // Persisted copy to avoid flash effect on page load
        statusIndicator: [
            null as StatusPageIndicator | null,
            { persist: true },
            {
                loadStatusPageSuccess: (_, { statusPage }) => statusPage.status.indicator,
                loadStatusPageFailure: () => 'none',
            },
        ],
    })),

    loaders(() => ({
        statusPage: [
            null as StatusPageResponse | null,
            {
                loadStatusPage: async () => {
                    const response = await fetch(`${STATUS_PAGE_BASE}/api/v2/status.json`)
                    const data: StatusPageResponse = await response.json()

                    return data
                },
            },
        ],
    })),

    listeners(({ actions, cache }) => ({
        loadStatusPageSuccess: () => {
            clearTimeout(cache.timeout)
            cache.timeout = setTimeout(() => actions.loadStatusPage(), REFRESH_INTERVAL)
        },
    })),

    afterMount(({ actions }) => {
        return actions.loadStatusPage()
    }),

    beforeUnmount(({ cache }) => {
        clearTimeout(cache.timeout)
    }),
])
