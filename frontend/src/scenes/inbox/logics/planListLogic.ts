import { afterMount, connect, kea, path } from 'kea'
import { loaders } from 'kea-loaders'

import { teamLogic } from 'scenes/teamLogic'

import { signalsPlansList } from 'products/signals/frontend/generated/api'
import type { InboxPlanReportApi } from 'products/signals/frontend/generated/api.schemas'

import type { planListLogicType } from './planListLogicType'

/**
 * Loads the Plan tab's list of plan reports ("projects"). Membership + ordering (most-recent-first)
 * come from the backend's ClickHouse lookup; this logic just fetches and holds the page. Read-only
 * for now — creation happens through the planning flow, not here.
 */
export const planListLogic = kea<planListLogicType>([
    path(['scenes', 'inbox', 'logics', 'planListLogic']),

    connect(() => ({
        values: [teamLogic, ['currentProjectId']],
    })),

    loaders(({ values }) => ({
        plans: [
            [] as InboxPlanReportApi[],
            {
                loadPlans: async () => {
                    const response = await signalsPlansList(String(values.currentProjectId))
                    return response.results
                },
            },
        ],
    })),

    afterMount(({ actions }) => {
        actions.loadPlans()
    }),
])
