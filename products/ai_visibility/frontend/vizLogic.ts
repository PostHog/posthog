import { actions, afterMount, beforeUnmount, kea, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import type { vizLogicType } from './vizLogicType'

export interface VizLogicProps {
    domain: string
}

interface StartedResponse {
    workflow_id: string
    status: 'started' | 'running'
}

interface ReadyResponse {
    status: 'ready'
    run_id: string
    domain: string
    results: Record<string, unknown>
}

type ApiResponse = StartedResponse | ReadyResponse

const POLL_INTERVAL_MS = 5000

export const vizLogic = kea<vizLogicType>([
    path(['products', 'ai_visibility', 'frontend', 'vizLogic']),
    props({} as VizLogicProps),

    actions({
        startPolling: true,
        stopPolling: true,
    }),

    loaders(({ props }) => ({
        triggerResult: [
            null as ApiResponse | null,
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
        pollIntervalId: [
            null as number | null,
            {
                startPolling: () => null,
                stopPolling: () => null,
            },
        ],
    }),

    selectors({
        workflowId: [
            (s) => [s.triggerResult],
            (triggerResult): string | null => {
                if (triggerResult?.status === 'started' || triggerResult?.status === 'running') {
                    return triggerResult.workflow_id
                }
                return null
            },
        ],
        isPolling: [
            (s) => [s.triggerResult],
            (triggerResult): boolean => triggerResult?.status === 'started' || triggerResult?.status === 'running',
        ],
        isReady: [(s) => [s.triggerResult], (triggerResult): boolean => triggerResult?.status === 'ready'],
        results: [
            (s) => [s.triggerResult],
            (triggerResult): Record<string, unknown> | null => {
                if (triggerResult?.status === 'ready') {
                    return triggerResult.results
                }
                return null
            },
        ],
        runId: [
            (s) => [s.triggerResult],
            (triggerResult): string | null => {
                if (triggerResult?.status === 'ready') {
                    return triggerResult.run_id
                }
                return null
            },
        ],
    }),

    listeners(({ actions, values, cache }) => ({
        loadTriggerResultSuccess: ({ triggerResult }) => {
            if (triggerResult?.status === 'started' || triggerResult?.status === 'running') {
                actions.startPolling()
            } else if (triggerResult?.status === 'ready') {
                actions.stopPolling()
            }
        },
        startPolling: () => {
            if (cache.pollIntervalId) {
                clearInterval(cache.pollIntervalId)
            }
            cache.pollIntervalId = setInterval(() => {
                if (!values.triggerResultLoading) {
                    actions.loadTriggerResult()
                }
            }, POLL_INTERVAL_MS)
        },
        stopPolling: () => {
            if (cache.pollIntervalId) {
                clearInterval(cache.pollIntervalId)
                cache.pollIntervalId = null
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadTriggerResult()
    }),

    beforeUnmount(({ cache }) => {
        if (cache.pollIntervalId) {
            clearInterval(cache.pollIntervalId)
        }
    }),
])
