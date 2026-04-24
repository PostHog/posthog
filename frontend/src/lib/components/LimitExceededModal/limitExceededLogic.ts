import { actions, kea, listeners, path, reducers, selectors } from 'kea'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'

import type { limitExceededLogicType } from './limitExceededLogicType'

export interface LimitIncreaseRequestPayload {
    id: string
    team_id: number
    team_name?: string
    status: 'pending' | 'approved' | 'denied'
    justification: string
    limit_key: string
    limit_description?: string
    limit_at_first_hit: number
    count_at_first_hit: number
    requested_value: number | null
    granted_value: number | null
    hit_count: number
    last_hit_at: string
    resolved_at: string | null
    resolution_note: string
}

export interface LimitExceededPayload {
    limit_key: string
    limit: number
    current: number
    request: { id: string } | null
}

export const limitExceededLogic = kea<limitExceededLogicType>([
    path(['lib', 'components', 'LimitExceededModal', 'limitExceededLogic']),
    actions({
        showLimitExceededModal: (payload: LimitExceededPayload, projectId: number) => ({
            payload,
            projectId,
        }),
        hideLimitExceededModal: true,
        setRequest: (request: LimitIncreaseRequestPayload | null) => ({ request }),
        saveJustification: (justification: string) => ({ justification }),
        setSaving: (saving: boolean) => ({ saving }),
    }),
    reducers({
        isOpen: [
            false,
            {
                showLimitExceededModal: () => true,
                hideLimitExceededModal: () => false,
            },
        ],
        limitExceededPayload: [
            null as LimitExceededPayload | null,
            {
                showLimitExceededModal: (_, { payload }) => payload,
                hideLimitExceededModal: () => null,
            },
        ],
        projectId: [
            null as number | null,
            {
                showLimitExceededModal: (_, { projectId }) => projectId,
                hideLimitExceededModal: () => null,
            },
        ],
        request: [
            null as LimitIncreaseRequestPayload | null,
            {
                setRequest: (_, { request }) => request,
                hideLimitExceededModal: () => null,
            },
        ],
        saving: [
            false,
            {
                setSaving: (_, { saving }) => saving,
            },
        ],
    }),
    selectors({
        requestId: [
            (s) => [s.request, s.limitExceededPayload],
            (request, payload): string | null => request?.id ?? payload?.request?.id ?? null,
        ],
        canEditJustification: [(s) => [s.request], (request): boolean => !request || request.status === 'pending'],
    }),
    listeners(({ actions, values }) => ({
        showLimitExceededModal: async ({ payload, projectId }) => {
            if (!payload.request) {
                return
            }
            try {
                const response = await api.get(
                    `api/projects/${projectId}/limit_increase_requests/${payload.request.id}/`
                )
                actions.setRequest(response as LimitIncreaseRequestPayload)
            } catch {
                // Non-fatal.
            }
        },
        saveJustification: async ({ justification }) => {
            const requestId = values.requestId
            const projectId = values.projectId
            if (!requestId || !projectId) {
                lemonToast.error(
                    `Cannot save context: missing ${!requestId ? 'request id' : 'project id'}. Close and retry.`
                )
                return
            }
            actions.setSaving(true)
            try {
                const response = await api.update(`api/projects/${projectId}/limit_increase_requests/${requestId}/`, {
                    justification,
                })
                actions.setRequest(response as LimitIncreaseRequestPayload)
                lemonToast.success('Context saved')
            } catch (e: any) {
                lemonToast.error(e?.detail ?? e?.message ?? 'Failed to save context.')
            } finally {
                actions.setSaving(false)
            }
        },
    })),
])
