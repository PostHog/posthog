import { actions, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import type { LimitIncreaseRequestPayload } from 'lib/components/LimitExceededModal/limitExceededLogic'

import type { limitRequestsLogicType } from './limitRequestsLogicType'

export const limitRequestsLogic = kea<limitRequestsLogicType>([
    path(['scenes', 'settings', 'environment', 'limitRequestsLogic']),
    actions({
        setProjectId: (projectId: number) => ({ projectId }),
        toggleExpanded: (id: string) => ({ id }),
        saveJustification: (id: string, justification: string) => ({ id, justification }),
        replaceRequest: (request: LimitIncreaseRequestPayload) => ({ request }),
        setSavingId: (id: string | null) => ({ id }),
    }),
    reducers({
        projectId: [
            null as number | null,
            {
                setProjectId: (_, { projectId }) => projectId,
            },
        ],
        expandedIds: [
            [] as string[],
            {
                toggleExpanded: (state, { id }) =>
                    state.includes(id) ? state.filter((x) => x !== id) : [...state, id],
            },
        ],
        savingId: [
            null as string | null,
            {
                setSavingId: (_, { id }) => id,
            },
        ],
    }),
    loaders(({ values }) => ({
        requests: [
            [] as LimitIncreaseRequestPayload[],
            {
                loadRequests: async (projectId: number) => {
                    const response = await api.get(`api/projects/${projectId}/limit_increase_requests/`)
                    return (response?.results ?? response ?? []) as LimitIncreaseRequestPayload[]
                },
                replaceRequest: ({ request }: { request: LimitIncreaseRequestPayload }) => {
                    return values.requests.map((r) => (r.id === request.id ? request : r))
                },
            },
        ],
    })),
    listeners(({ actions, values }) => ({
        saveJustification: async ({ id, justification }) => {
            const projectId = values.projectId
            if (!projectId) {
                lemonToast.error('No project selected, cannot save.')
                return
            }
            actions.setSavingId(id)
            try {
                const updated = await api.update(`api/projects/${projectId}/limit_increase_requests/${id}/`, {
                    justification,
                })
                actions.replaceRequest(updated as LimitIncreaseRequestPayload)
                lemonToast.success('Context saved')
            } catch (e: any) {
                lemonToast.error(e?.detail ?? e?.message ?? 'Failed to save context.')
            } finally {
                actions.setSavingId(null)
            }
        },
    })),
])
