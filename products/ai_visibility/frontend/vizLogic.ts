import { afterMount, kea, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import type { vizLogicType } from './vizLogicType'

export interface VizLogicProps {
    domain: string
}

interface TriggerResponse {
    workflow_id: string
    status: string
}

export const vizLogic = kea<vizLogicType>([
    path(['products', 'ai_visibility', 'frontend', 'vizLogic']),
    props({} as VizLogicProps),

    loaders(({ props }) => ({
        triggerResult: [
            null as TriggerResponse | null,
            {
                loadTriggerResult: async () => {
                    if (!props.domain) {
                        throw new Error('Domain missing')
                    }
                    const response = await fetch('/api/ai_visibility/', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ domain: props.domain }),
                    })
                    if (!response.ok) {
                        const data = await response.json().catch(() => ({}))
                        const message = data?.error || `Request failed with status ${response.status}`
                        throw new Error(message)
                    }
                    return await response.json()
                },
            },
        ],
    })),

    reducers({
        lastError: [
            null as string | null,
            {
                loadTriggerResultFailure: (_, { error }) => error?.message ?? 'Failed to start workflow',
                loadTriggerResultSuccess: () => null,
            },
        ],
    }),

    selectors({
        workflowId: [(s) => [s.triggerResult], (triggerResult): string | null => triggerResult?.workflow_id ?? null],
        workflowStatus: [(s) => [s.triggerResult], (triggerResult): string | null => triggerResult?.status ?? null],
    }),

    afterMount(({ actions }) => {
        actions.loadTriggerResult()
    }),
])
